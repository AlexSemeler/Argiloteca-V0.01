"""One persistent stdio MCP child, serialized calls, bounded queue and deadlines."""
import asyncio
import concurrent.futures
import os
import sys
import threading
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPUnavailable(Exception):
    pass


class MCPBridge:
    def __init__(self):
        self.guard = threading.Lock(); self.ready = threading.Event(); self.slots = threading.BoundedSemaphore(4)
        self.thread = None; self.loop = None; self.queue = None; self.tools = []; self.error = None
        self.pending = set()

    def start(self):
        with self.guard:
            if not self.thread or not self.thread.is_alive():
                self.ready.clear(); self.error = None
                self.thread = threading.Thread(target=self._thread, daemon=True, name="argiloclay-mcp")
                self.thread.start()
        if not self.ready.wait(4) or self.error:
            raise MCPUnavailable("MCP indisponível.")

    def _thread(self):
        try: asyncio.run(self._serve())
        except Exception:
            self.error = True; self.ready.set()
            with self.guard: pending = list(self.pending)
            for future in pending:
                if not future.done(): future.set_exception(MCPUnavailable("MCP desconectado."))

    async def _serve(self):
        params = StdioServerParameters(command=sys.executable, args=["-m", "argiloclay_intelligence.mcp_server"], env=dict(os.environ))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize(); self.tools = [t.name for t in (await session.list_tools()).tools]
                self.loop = asyncio.get_running_loop(); self.queue = asyncio.Queue(maxsize=4); self.ready.set()
                while True:
                    name, arguments, future = await self.queue.get()
                    try:
                        if future.cancelled(): continue
                        result = await asyncio.wait_for(session.call_tool(name, arguments), timeout=5)
                        if result.isError: raise MCPUnavailable("Ferramenta recusou a consulta.")
                        import json
                        payload = json.loads(result.content[0].text)
                        if not isinstance(payload, dict): raise MCPUnavailable("Resposta MCP inválida.")
                        if not future.done(): future.set_result(payload)
                    except Exception:
                        if not future.done(): future.set_exception(MCPUnavailable("Consulta MCP indisponível."))
                    finally:
                        self.queue.task_done()

    def _enqueue(self, item):
        try: self.queue.put_nowait(item)
        except asyncio.QueueFull:
            if not item[2].done(): item[2].set_exception(MCPUnavailable("MCP ocupado."))

    def call(self, name, arguments):
        self.start()
        if name not in self.tools or not self.slots.acquire(blocking=False):
            raise MCPUnavailable("MCP ocupado ou ferramenta desconhecida.")
        future = concurrent.futures.Future()
        with self.guard: self.pending.add(future)
        def release(_):
            with self.guard: self.pending.discard(future)
            self.slots.release()
        future.add_done_callback(release)
        try:
            self.loop.call_soon_threadsafe(self._enqueue, (name, arguments, future))
        except RuntimeError as exc:
            future.cancel(); raise MCPUnavailable("MCP desconectado.") from exc
        try: return future.result(timeout=6)
        except concurrent.futures.TimeoutError as exc:
            future.cancel(); raise MCPUnavailable("Prazo MCP excedido.") from exc
