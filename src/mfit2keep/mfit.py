"""Cliente assíncrono da API do MFIT Personal.

A API foi mapeada a partir do bundle do SPA (client.mfitpersonal.com.br):

    POST {BASE}/auth/client        {"mail": ..., "senha": ...}  -> {"token": "<jwt>"}
    GET  {BASE}/v2/client/workout/all
    GET  {BASE}/v2/client/workout/?id=<rotinaId>
    GET  {BASE}/v2/client/workout/session?id=<diaId>

Todas as rotas autenticadas usam o header ``authorization: <jwt>`` — sem o
prefixo ``Bearer``. O SPA guarda esse mesmo JWT no cookie ``client_token``.
"""

import asyncio
import json
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import httpx

from .config import STATE_DIR, Settings
from .secure_io import read_secret_json, write_secret_json

type Json = Any

BASE_URL = "https://api.mfitpersonal.com.br"
TIMEOUT = httpx.Timeout(20.0)
#: Reenvio só para o que é transitório; 4xx sobe na hora.
RETRIABLE_STATUS = frozenset({429, 500, 502, 503, 504})
RETRY_ATTEMPTS = 3
RETRY_INITIAL_DELAY = 1.0
TOKEN_CACHE = STATE_DIR / "mfit_token.json"


class MfitError(RuntimeError):
    """Erro vindo da API do MFIT."""


class MfitClient:
    """Wrapper fino sobre a API do MFIT, com cache de token em disco.

    O login é serializado por um lock: várias requisições concorrentes que
    esbarram num token expirado renovam uma vez só.
    """

    def __init__(self, settings: Settings, *, base_url: str = BASE_URL) -> None:
        self._settings = settings
        self._base_url = base_url.rstrip("/")
        self._token: str | None = settings.token
        self._auth_lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            headers={"Content-Type": "application/json"},
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=10),
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ auth

    async def token(self) -> str:
        if self._token is None:
            async with self._auth_lock:
                if self._token is None:  # outro coroutine pode ter renovado
                    self._token = self._cached_token() or await self._login()
        return self._token

    def _cached_token(self) -> str | None:
        """Cache corrompido é cache-miss, nunca exceção.

        ``read_secret_json`` já rejeita o que não for objeto JSON: um arquivo
        truncado (disco com bad block, escrita interrompida) precisa levar a um
        login novo, não derrubar o comando.
        """
        cached = (read_secret_json(TOKEN_CACHE) or {}).get("token")
        return cached if isinstance(cached, str) and cached else None

    def _store_token(self, token: str) -> None:
        # O JWT do MFIT vale ~400 dias: nasce 0600, sem passar por 0664.
        write_secret_json(TOKEN_CACHE, {"token": token})

    async def _login(self) -> str:
        email, password = self._settings.require_credentials()
        response = await self._client.post(
            f"{self._base_url}/auth/client",
            json={"mail": email, "senha": password},
        )
        if response.status_code >= 400:
            raise MfitError(f"Login falhou ({response.status_code}): {_message(response)}")

        token = response.json().get("token")
        if not isinstance(token, str) or not token:
            raise MfitError("Login não retornou token.")

        self._store_token(token)
        return token

    async def _forget_token(self) -> None:
        async with self._auth_lock:
            self._token = None
            TOKEN_CACHE.unlink(missing_ok=True)

    # ---------------------------------------------------------------- requests

    async def _get(self, path: str) -> Json:
        """GET autenticado, refazendo o login uma vez se o token expirou."""
        response = await self._authenticated_get(path)

        if response.status_code in (401, 403):
            # O token vale ~400 dias, mas o professor pode revogar o acesso a qualquer momento.
            await self._forget_token()
            response = await self._authenticated_get(path)

        if response.status_code >= 400:
            raise MfitError(f"GET {path} falhou ({response.status_code}): {_message(response)}")
        return response.json()

    async def _authenticated_get(self, path: str) -> httpx.Response:
        """GET com backoff: falha transitória de rede não pode abortar o sync.

        Só reenvia o que é seguro reenviar — GET é idempotente — e só para
        erro de transporte, 429 e 5xx. 4xx de verdade sobe na hora.
        """
        delay = RETRY_INITIAL_DELAY
        last_error: Exception | None = None

        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                response = await self._client.get(
                    f"{self._base_url}{path}",
                    headers={"authorization": await self.token()},
                )
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if response.status_code not in RETRIABLE_STATUS:
                    return response
                last_error = MfitError(f"GET {path} devolveu {response.status_code}")

            if attempt == RETRY_ATTEMPTS:
                break
            await asyncio.sleep(delay)
            delay *= 2

        raise MfitError(f"GET {path} falhou após {RETRY_ATTEMPTS} tentativas: {last_error}")

    # -------------------------------------------------------------- endpoints

    async def list_workouts(self) -> Json:
        """Todas as rotinas do aluno (payload cru da API)."""
        return await self._get("/v2/client/workout/all")

    async def workout_details(self, routine_id: int | str) -> Json:
        """Rotina: metadados + a lista de dias em ``workouts`` (sem exercícios)."""
        return await self._get(f"/v2/client/workout/?id={routine_id}")

    async def workout_session(self, day_id: int | str) -> Json:
        """Um dia de treino com os exercícios e séries em ``exercs``."""
        return await self._get(f"/v2/client/workout/session?id={day_id}")

    async def workout_sessions(self, day_ids: list[int | str]) -> dict[str, Json]:
        """Busca vários dias de uma vez — é aqui que o async paga a conta."""
        async with asyncio.TaskGroup() as group:
            tasks = {str(i): group.create_task(self.workout_session(i)) for i in day_ids}
        return {day_id: task.result() for day_id, task in tasks.items()}


def _message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(payload, dict):
        return str(payload.get("message") or payload)[:300]
    return str(payload)[:300]


async def dump_raw(settings: Settings, routine_id: int | str | None, out_dir: Path) -> list[Path]:
    """Salva os payloads crus em disco — usado para inspecionar o formato real."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    async with MfitClient(settings) as client:
        payloads: dict[str, Json] = {"workout_all": await client.list_workouts()}
        if routine_id is not None:
            routine = await client.workout_details(routine_id)
            payloads[f"workout_{routine_id}"] = routine
            day_ids = [d["id"] for d in routine.get("workouts") or [] if d.get("id") is not None]
            for day_id, session in (await client.workout_sessions(day_ids)).items():
                payloads[f"session_{day_id}"] = session

    for name, payload in payloads.items():
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path)
    return written
