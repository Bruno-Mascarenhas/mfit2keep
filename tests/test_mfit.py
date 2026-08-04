import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from mfit2keep import mfit
from mfit2keep.config import ConfigError, Settings
from mfit2keep.mfit import BASE_URL, MfitClient, MfitError
from mfit2keep.sync import fetch_workouts

from .conftest import exercise, group


@pytest.fixture(autouse=True)
def isolated_token_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nenhum teste pode ler nem escrever o token real do usuário."""
    monkeypatch.setattr(mfit, "TOKEN_CACHE", tmp_path / "mfit_token.json")


@respx.mock
async def test_login_posts_credentials_and_returns_token(settings: Settings) -> None:
    route = respx.post(f"{BASE_URL}/auth/client").mock(
        return_value=httpx.Response(200, json={"token": "jwt-123"})
    )

    async with MfitClient(settings) as client:
        assert await client.token() == "jwt-123"

    # A API espera exatamente estes nomes de campo, em português.
    assert json.loads(route.calls.last.request.read()) == {
        "mail": "aluno@exemplo.com",
        "senha": "segredo",
    }


@respx.mock
async def test_authenticated_get_sends_raw_jwt_without_bearer(settings: Settings) -> None:
    respx.post(f"{BASE_URL}/auth/client").mock(
        return_value=httpx.Response(200, json={"token": "jwt-123"})
    )
    route = respx.get(f"{BASE_URL}/v2/client/workout/all").mock(
        return_value=httpx.Response(200, json=[])
    )

    async with MfitClient(settings) as client:
        await client.list_workouts()

    # A API do MFIT rejeita "Bearer <jwt>"; o header é o token cru.
    assert route.calls.last.request.headers["authorization"] == "jwt-123"


@respx.mock
async def test_login_happens_once_for_concurrent_requests(settings: Settings) -> None:
    login = respx.post(f"{BASE_URL}/auth/client").mock(
        return_value=httpx.Response(200, json={"token": "jwt-123"})
    )
    respx.get(url__startswith=f"{BASE_URL}/v2/client/workout/session").mock(
        return_value=httpx.Response(200, json={"id": 1, "nome": "X", "exercs": []})
    )

    async with MfitClient(settings) as client:
        await client.workout_sessions([1, 2, 3, 4, 5])

    assert login.call_count == 1


@respx.mock
async def test_expired_token_triggers_one_relogin(settings: Settings) -> None:
    login = respx.post(f"{BASE_URL}/auth/client").mock(
        side_effect=[
            httpx.Response(200, json={"token": "velho"}),
            httpx.Response(200, json={"token": "novo"}),
        ]
    )
    workouts = respx.get(f"{BASE_URL}/v2/client/workout/all").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json=[{"id": 1}])]
    )

    async with MfitClient(settings) as client:
        assert await client.list_workouts() == [{"id": 1}]

    assert login.call_count == 2
    assert workouts.calls[-1].request.headers["authorization"] == "novo"


@respx.mock
async def test_persistent_401_raises(settings: Settings) -> None:
    respx.post(f"{BASE_URL}/auth/client").mock(
        return_value=httpx.Response(200, json={"token": "jwt"})
    )
    respx.get(f"{BASE_URL}/v2/client/workout/all").mock(return_value=httpx.Response(401))

    async with MfitClient(settings) as client:
        with pytest.raises(MfitError, match=r"falhou \(401\)"):
            await client.list_workouts()


@respx.mock
async def test_login_failure_surfaces_api_message(settings: Settings) -> None:
    respx.post(f"{BASE_URL}/auth/client").mock(
        return_value=httpx.Response(401, json={"message": "Senha inválida"})
    )

    async with MfitClient(settings) as client:
        with pytest.raises(MfitError, match="Senha inválida"):
            await client.token()


async def test_missing_credentials_raise_config_error() -> None:
    async with MfitClient(Settings(email=None, password=None, token=None)) as client:
        with pytest.raises(ConfigError, match="MFIT_EMAIL"):
            await client.token()


@respx.mock
async def test_explicit_token_skips_login(settings: Settings) -> None:
    login = respx.post(f"{BASE_URL}/auth/client")
    respx.get(f"{BASE_URL}/v2/client/workout/all").mock(return_value=httpx.Response(200, json=[]))

    async with MfitClient(Settings(email=None, password=None, token="do-navegador")) as client:
        await client.list_workouts()

    assert login.call_count == 0


@respx.mock
async def test_token_is_cached_across_clients(settings: Settings, tmp_path: Path) -> None:
    login = respx.post(f"{BASE_URL}/auth/client").mock(
        return_value=httpx.Response(200, json={"token": "jwt-123"})
    )

    async with MfitClient(settings) as first:
        await first.token()
    async with MfitClient(settings) as second:
        assert await second.token() == "jwt-123"

    assert login.call_count == 1


@respx.mock
async def test_fetch_workouts_pulls_every_day(settings: Settings, routine: dict[str, Any]) -> None:
    respx.post(f"{BASE_URL}/auth/client").mock(
        return_value=httpx.Response(200, json={"token": "jwt"})
    )
    respx.get(url__startswith=f"{BASE_URL}/v2/client/workout/?id=").mock(
        return_value=httpx.Response(200, json=routine)
    )
    names = {156902750: "Bíceps/Triceps", 156902751: "Costa"}
    sessions = respx.get(url__startswith=f"{BASE_URL}/v2/client/workout/session").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json={
                "id": (day_id := int(request.url.params["id"])),
                "nome": names[day_id],
                "exercs": [group(exercise("Supino"))],
            },
        )
    )

    workouts = await fetch_workouts(MfitClient(settings), 36318803)

    # Um GET por dia, todos disparados juntos pelo TaskGroup.
    assert sessions.call_count == 2
    assert [w.title for w in workouts] == ["A — Bíceps/Triceps", "B — Costa"]


@respx.mock
async def test_workout_without_days_is_parsed_as_a_single_session(settings: Settings) -> None:
    respx.post(f"{BASE_URL}/auth/client").mock(
        return_value=httpx.Response(200, json={"token": "jwt"})
    )
    respx.get(url__startswith=f"{BASE_URL}/v2/client/workout/?id=").mock(
        return_value=httpx.Response(
            200, json={"id": 7, "nome": "Treino avulso", "exercs": [group(exercise("Supino"))]}
        )
    )

    workouts = await fetch_workouts(MfitClient(settings), 7)

    assert len(workouts) == 1
    assert workouts[0].name == "Treino avulso"


@pytest.fixture(autouse=True)
def instant_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem espera real: o teste verifica a política de retry, não o relógio."""
    monkeypatch.setattr(mfit, "RETRY_INITIAL_DELAY", 0.0)


@respx.mock
async def test_transient_network_error_is_retried(settings: Settings) -> None:
    respx.post(f"{BASE_URL}/auth/client").mock(
        return_value=httpx.Response(200, json={"token": "jwt"})
    )
    route = respx.get(f"{BASE_URL}/v2/client/workout/all").mock(
        side_effect=[httpx.ConnectError("rede caiu"), httpx.Response(200, json=[{"id": 1}])]
    )

    async with MfitClient(settings) as client:
        assert await client.list_workouts() == [{"id": 1}]

    assert route.call_count == 2


@respx.mock
async def test_server_error_is_retried(settings: Settings) -> None:
    respx.post(f"{BASE_URL}/auth/client").mock(
        return_value=httpx.Response(200, json={"token": "jwt"})
    )
    route = respx.get(f"{BASE_URL}/v2/client/workout/all").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=[])]
    )

    async with MfitClient(settings) as client:
        await client.list_workouts()

    assert route.call_count == 2


@respx.mock
async def test_rate_limit_is_retried(settings: Settings) -> None:
    respx.post(f"{BASE_URL}/auth/client").mock(
        return_value=httpx.Response(200, json={"token": "jwt"})
    )
    route = respx.get(f"{BASE_URL}/v2/client/workout/all").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json=[])]
    )

    async with MfitClient(settings) as client:
        await client.list_workouts()

    assert route.call_count == 2


@respx.mock
async def test_client_error_is_not_retried(settings: Settings) -> None:
    respx.post(f"{BASE_URL}/auth/client").mock(
        return_value=httpx.Response(200, json={"token": "jwt"})
    )
    route = respx.get(f"{BASE_URL}/v2/client/workout/all").mock(
        return_value=httpx.Response(404, json={"message": "não existe"})
    )

    async with MfitClient(settings) as client:
        with pytest.raises(MfitError, match="404"):
            await client.list_workouts()

    # 404 não é transitório: reenviar só gastaria tempo.
    assert route.call_count == 1


@respx.mock
async def test_retry_gives_up_and_reports(settings: Settings) -> None:
    respx.post(f"{BASE_URL}/auth/client").mock(
        return_value=httpx.Response(200, json={"token": "jwt"})
    )
    route = respx.get(f"{BASE_URL}/v2/client/workout/all").mock(
        side_effect=httpx.ConnectError("rede fora")
    )

    async with MfitClient(settings) as client:
        with pytest.raises(MfitError, match="após 3 tentativas"):
            await client.list_workouts()

    assert route.call_count == 3


async def test_corrupted_token_cache_is_a_cache_miss(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache = tmp_path / "mfit_token.json"
    # JSON válido, mas não é objeto: um arquivo truncado por bad block gera isso.
    cache.write_text('["nao-e-um-objeto"]', encoding="utf-8")
    monkeypatch.setattr(mfit, "TOKEN_CACHE", cache)

    with respx.mock:
        respx.post(f"{BASE_URL}/auth/client").mock(
            return_value=httpx.Response(200, json={"token": "novo"})
        )
        async with MfitClient(settings) as client:
            # Cache ruim tem que virar login novo, não TypeError.
            assert await client.token() == "novo"
