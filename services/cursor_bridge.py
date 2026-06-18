"""
Cursor-мост через Cloud Agents API (https://api.cursor.com/v1).

Работает на Railway и локально: бот шлёт задачи в облачного агента Cursor,
который клонирует GitHub-репозиторий проекта, правит код и (опционально)
открывает PR. Ответ возвращается в Telegram.

Нужно:
  • CURSOR_API_KEY — User API Key из Cursor Dashboard → Integrations
  • CURSOR_REPO_URL — GitHub-репозиторий (должен быть подключён к Cursor)
  • CURSOR_REPO_REF — ветка-основа (обычно main)

Сессия: /cursor включает режим → текстовые сообщения уходят агенту.
Первое сообщение создаёт агента, следующие — follow-up в тот же диалог.
"""
from __future__ import annotations

import asyncio
import base64
from typing import Any, Optional

import aiohttp
from loguru import logger

API_BASE = "https://api.cursor.com/v1"
DEFAULT_REPO = "https://github.com/ciseuadm/Manager-S-Rank"
DEFAULT_REF = "main"

MODEL_CHOICES = ("auto", "sonnet", "opus", "max")
MODEL_LABELS = {
    "auto": "🎲 Auto (Cursor сам выбирает)",
    "sonnet": "⚡ Sonnet 4.6",
    "opus": "🧠 Opus 4.8",
    "max": "🚀 MAX (для крупных задач)",
}

_TERMINAL = frozenset({"FINISHED", "ERROR", "CANCELLED", "EXPIRED"})
_RUNNING = frozenset({"CREATING", "RUNNING", "PENDING"})


class CursorBridge:
    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._agent_id: str | None = None
        self._models_cache: list[dict] | None = None
        self._lock = asyncio.Lock()
        self._api_key: str = ""
        self._repo_url: str = DEFAULT_REPO
        self._repo_ref: str = DEFAULT_REF
        self._auto_pr: bool = True
        self._model_sonnet: str = "claude-sonnet-4-6"
        self._model_opus: str = "claude-opus-4-8"
        self.active: bool = False
        self.busy: bool = False
        self.model_choice: str = "auto"

    # ── Конфигурация ─────────────────────────────────────────────────────────

    def configure(
        self,
        api_key: str,
        repo_url: str = "",
        repo_ref: str = "",
        auto_pr: bool = True,
        model_sonnet: str = "",
        model_opus: str = "",
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._repo_url = (repo_url or DEFAULT_REPO).strip()
        self._repo_ref = (repo_ref or DEFAULT_REF).strip()
        self._auto_pr = auto_pr
        self._model_sonnet = model_sonnet or "claude-sonnet-4-6"
        self._model_opus = model_opus or "claude-opus-4-8"

    def available(self) -> bool:
        return bool(self._api_key and self._repo_url)

    def status_text(self) -> str:
        if not self._api_key:
            return (
                "⚠️ Не задан <code>CURSOR_API_KEY</code>.\n"
                "Добавь ключ в Railway Variables (или .env локально):\n"
                "https://cursor.com/dashboard/integrations"
            )
        if not self._repo_url:
            return "⚠️ Не задан <code>CURSOR_REPO_URL</code> (GitHub-репозиторий)."
        state = "🟢 включён" if self.active else "⚪️ выключен"
        pr = "да" if self._auto_pr else "нет"
        return (
            f"🛰 <b>Cursor-мост</b> (облако): {state}\n"
            f"Модель: <b>{MODEL_LABELS.get(self.model_choice, self.model_choice)}</b>\n"
            f"Репозиторий: <code>{self._repo_url}</code>\n"
            f"Ветка: <code>{self._repo_ref}</code> · PR автоматически: <b>{pr}</b>"
        )

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def _auth_header(self) -> dict[str, str]:
        # Basic auth: api_key as username, empty password (как в доке Cursor).
        token = base64.b64encode(f"{self._api_key}:".encode()).decode()
        return {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=600, connect=30)
            self._session = aiohttp.ClientSession(
                headers=self._auth_header(),
                timeout=timeout,
            )
        return self._session

    async def _api(
        self, method: str, path: str, body: dict | None = None
    ) -> tuple[int, Any]:
        session = await self._ensure_session()
        url = f"{API_BASE}{path}"
        async with session.request(method, url, json=body) as resp:
            try:
                data = await resp.json()
            except Exception:
                data = await resp.text()
            if resp.status >= 400:
                logger.warning(f"[CURSOR] API {method} {path} → {resp.status}: {data}")
            return resp.status, data

    # ── Модели ───────────────────────────────────────────────────────────────

    async def _fetch_models(self) -> list[dict]:
        if self._models_cache is not None:
            return self._models_cache
        status, data = await self._api("GET", "/models")
        if status != 200 or not isinstance(data, dict):
            self._models_cache = []
            return []
        self._models_cache = list(data.get("items") or [])
        return self._models_cache

    def _find_model(self, models: list[dict], *needles: str) -> dict | None:
        for m in models:
            hay = f"{m.get('id', '')} {m.get('displayName', '')}".lower()
            if all(n.lower() in hay for n in needles):
                return m
        return None

    def _build_model_payload(self, choice: str, models: list[dict]) -> dict | None:
        """None → Auto (поле model не отправляем)."""
        if choice == "auto":
            return None

        if choice in ("opus", "max"):
            mid = self._model_opus
            mobj = self._find_model(models, "opus") if models else None
        else:
            mid = self._model_sonnet
            mobj = self._find_model(models, "sonnet") if models else None

        model_id = (mobj or {}).get("id") or mid
        payload: dict[str, Any] = {"id": model_id}

        if choice != "max" or not mobj:
            return payload

        params = []
        for pdef in mobj.get("parameters") or []:
            pid = (pdef.get("id") or "").lower()
            values = [v.get("value") for v in (pdef.get("values") or []) if v.get("value")]
            if not values:
                continue
            chosen = None
            if pid == "effort":
                chosen = "max" if "max" in values else values[-1]
            elif pid == "context":
                chosen = values[-1]
            elif pid == "thinking":
                chosen = "true" if "true" in values else values[-1]
            if chosen is not None:
                params.append({"id": pdef.get("id"), "value": chosen})
        if params:
            payload["params"] = params
        return payload

    # ── Агент и runs ───────────────────────────────────────────────────────────

    async def _create_agent(self, prompt: str) -> tuple[str, str]:
        """Создать cloud-агента. Возвращает (agent_id, run_id)."""
        models = await self._fetch_models()
        body: dict[str, Any] = {
            "prompt": {"text": prompt},
            "repos": [{"url": self._repo_url, "startingRef": self._repo_ref}],
            "autoCreatePR": self._auto_pr,
            "skipReviewerRequest": True,
        }
        model = self._build_model_payload(self.model_choice, models)
        if model:
            body["model"] = model

        status, data = await self._api("POST", "/agents", body)
        if status not in (200, 201) or not isinstance(data, dict):
            err = data if isinstance(data, str) else (data.get("message") or data)
            raise RuntimeError(f"Не удалось создать агента ({status}): {err}")

        agent = data.get("agent") or {}
        run = data.get("run") or {}
        agent_id = agent.get("id") or ""
        run_id = run.get("id") or ""
        if not agent_id or not run_id:
            raise RuntimeError("Cursor вернул пустой agent/run id")
        logger.info(f"[CURSOR] agent created {agent_id}, run {run_id}")
        return agent_id, run_id

    async def _create_run(self, agent_id: str, prompt: str) -> str:
        status, data = await self._api(
            "POST", f"/agents/{agent_id}/runs", {"prompt": {"text": prompt}}
        )
        if status == 409:
            raise RuntimeError("Агент занят предыдущей задачей. Подожди или нажми «Новый диалог».")
        if status not in (200, 201) or not isinstance(data, dict):
            err = data if isinstance(data, str) else (data.get("message") or data)
            raise RuntimeError(f"Не удалось отправить задачу ({status}): {err}")
        run_id = (data.get("run") or {}).get("id") or ""
        if not run_id:
            raise RuntimeError("Cursor не вернул run id")
        logger.info(f"[CURSOR] follow-up run {run_id} on agent {agent_id}")
        return run_id

    async def _poll_run(self, agent_id: str, run_id: str) -> dict:
        """Ждём завершения run, опрашивая каждые 4 сек."""
        for _ in range(450):  # ~30 мин максимум
            status, data = await self._api("GET", f"/agents/{agent_id}/runs/{run_id}")
            if status != 200 or not isinstance(data, dict):
                await asyncio.sleep(4)
                continue
            st = (data.get("status") or "").upper()
            if st in _TERMINAL:
                return data
            if st in _RUNNING or not st:
                await asyncio.sleep(4)
                continue
            await asyncio.sleep(4)
        raise TimeoutError("Агент не ответил за 30 минут. Проверь статус в Cursor Dashboard.")

    @staticmethod
    def _format_result(run: dict) -> str:
        text = (run.get("result") or "").strip()
        st = (run.get("status") or "").upper()
        if st == "ERROR":
            return text or "Агент завершился с ошибкой."
        if st in ("CANCELLED", "EXPIRED"):
            return text or f"Задача прервана ({st})."

        extras: list[str] = []
        git = run.get("git") or {}
        for b in git.get("branches") or []:
            if b.get("prUrl"):
                extras.append(f"🔗 PR: {b['prUrl']}")
            elif b.get("branch"):
                repo = b.get("repoUrl", "")
                extras.append(f"🌿 Ветка: {b['branch']}" + (f" ({repo})" if repo else ""))

        agent_url = run.get("agentUrl") or run.get("url")
        if not extras and not text:
            return "(агент завершил работу без текстового ответа)"
        parts = [text] if text else []
        if extras:
            parts.extend(["", *extras])
        dur = run.get("durationMs")
        if dur:
            parts.append(f"\n⏱ {dur // 1000} сек")
        return "\n".join(parts).strip()

    # ── Публичный API ──────────────────────────────────────────────────────────

    def start_session(self) -> None:
        self.active = True

    async def stop_session(self) -> None:
        self.active = False
        self._agent_id = None

    async def new_dialog(self) -> None:
        self._agent_id = None

    async def set_model(self, choice: str) -> None:
        if choice not in MODEL_CHOICES:
            return
        if choice != self.model_choice:
            self.model_choice = choice
            self._agent_id = None

    async def run_task(self, prompt: str) -> tuple[bool, str]:
        if self.busy:
            return False, "⏳ Агент занят другой задачей. Дождись ответа."

        async with self._lock:
            self.busy = True
            try:
                if self._agent_id:
                    run_id = await self._create_run(self._agent_id, prompt)
                    agent_id = self._agent_id
                else:
                    agent_id, run_id = await self._create_agent(prompt)
                    self._agent_id = agent_id

                run = await self._poll_run(agent_id, run_id)
                st = (run.get("status") or "").upper()
                text = self._format_result(run)
                if st == "FINISHED":
                    return True, text
                return False, text
            except Exception as e:
                logger.exception(f"[CURSOR] run failed: {e}")
                # Сброс агента при ошибке — следующая попытка создаст нового.
                self._agent_id = None
                return False, str(e)
            finally:
                self.busy = False

    async def list_models_text(self) -> str:
        models = await self._fetch_models()
        if not models:
            return "Не удалось получить список моделей (проверь ключ и доступ к API)."
        lines = ["🤖 <b>Доступные модели Cursor (облако)</b>\n"]
        for m in models[:40]:
            mid = m.get("id", "?")
            dn = m.get("displayName", "") or ""
            has_max = any(
                (p.get("id") or "").lower() == "effort"
                and any(v.get("value") == "max" for v in (p.get("values") or []))
                for p in (m.get("parameters") or [])
            )
            lines.append(f"• <code>{mid}</code> — {dn}{' · MAX' if has_max else ''}")
        return "\n".join(lines)

    async def close(self) -> None:
        self._agent_id = None
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None


bridge = CursorBridge()
