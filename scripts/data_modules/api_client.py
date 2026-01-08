#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data Modules - API 客户端
只负责 Embedding 和 Rerank，LLM 调用由 Agent 完成
"""

import asyncio
import aiohttp
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from .config import get_config


@dataclass
class APIStats:
    """API 调用统计"""
    total_calls: int = 0
    total_time: float = 0.0
    errors: int = 0


class ModalAPIClient:
    """Modal 云端 API 客户端 - Embedding + Rerank"""

    def __init__(self, config=None):
        self.config = config or get_config()
        self.sem_embed = asyncio.Semaphore(self.config.embed_concurrency)
        self.sem_rerank = asyncio.Semaphore(self.config.rerank_concurrency)

        self.stats = {
            "embed": APIStats(),
            "rerank": APIStats()
        }

        self._warmed_up = {"embed": False, "rerank": False}
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=200, limit_per_host=100)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ==================== 预热 ====================

    async def warmup(self):
        """预热 Embedding 和 Rerank 服务"""
        print("[WARMUP] Warming up Embed + Rerank...")
        start = time.time()

        tasks = [self._warmup_embed(), self._warmup_rerank()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for name, result in zip(["Embed", "Rerank"], results):
            if isinstance(result, Exception):
                print(f"  [FAIL] {name}: {result}")
            else:
                print(f"  [OK] {name} ready")

        print(f"[WARMUP] Done in {time.time() - start:.1f}s")

    async def _warmup_embed(self):
        await self.embed(["test"])
        self._warmed_up["embed"] = True

    async def _warmup_rerank(self):
        await self.rerank("test", ["doc1", "doc2"])
        self._warmed_up["rerank"] = True

    # ==================== Embedding API ====================

    async def embed(self, texts: List[str]) -> Optional[List[List[float]]]:
        """调用 Embedding 服务"""
        if not texts:
            return []

        timeout = self.config.cold_start_timeout if not self._warmed_up["embed"] else self.config.normal_timeout

        async with self.sem_embed:
            start = time.time()
            session = await self._get_session()

            try:
                payload = {"input": texts, "model": "qwen-embedding"}

                async with session.post(
                    self.config.embed_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        embeddings = [item["embedding"] for item in data["data"]]

                        self.stats["embed"].total_calls += 1
                        self.stats["embed"].total_time += time.time() - start

                        return embeddings
                    else:
                        self.stats["embed"].errors += 1
                        print(f"[ERR] Embed {resp.status}")
                        return None

            except Exception as e:
                self.stats["embed"].errors += 1
                print(f"[ERR] Embed: {e}")
                return None

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """分批 Embedding"""
        all_embeddings = []
        batch_size = self.config.embed_batch_size

        batches = [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]
        tasks = [self.embed(batch) for batch in batches]
        results = await asyncio.gather(*tasks)

        for result in results:
            if result:
                all_embeddings.extend(result)
            else:
                # 失败时填充零向量
                all_embeddings.extend([[0.0] * 4096] * batch_size)

        return all_embeddings[:len(texts)]

    # ==================== Rerank API ====================

    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """调用 Rerank 服务"""
        if not documents:
            return []

        timeout = self.config.cold_start_timeout if not self._warmed_up["rerank"] else self.config.normal_timeout

        async with self.sem_rerank:
            start = time.time()
            session = await self._get_session()

            try:
                payload = {"query": query, "documents": documents}
                if top_n:
                    payload["top_n"] = top_n

                async with session.post(
                    self.config.rerank_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()

                        self.stats["rerank"].total_calls += 1
                        self.stats["rerank"].total_time += time.time() - start

                        return data.get("results", [])
                    else:
                        self.stats["rerank"].errors += 1
                        print(f"[ERR] Rerank {resp.status}")
                        return None

            except Exception as e:
                self.stats["rerank"].errors += 1
                print(f"[ERR] Rerank: {e}")
                return None

    # ==================== 统计 ====================

    def print_stats(self):
        print("\n[API STATS]")
        for name, stats in self.stats.items():
            if stats.total_calls > 0:
                avg_time = stats.total_time / stats.total_calls
                print(f"  {name.upper()}: {stats.total_calls} calls, "
                      f"{stats.total_time:.1f}s total, "
                      f"{avg_time:.2f}s avg, "
                      f"{stats.errors} errors")


# 全局客户端
_client: Optional[ModalAPIClient] = None


def get_client(config=None) -> ModalAPIClient:
    global _client
    if _client is None or config is not None:
        _client = ModalAPIClient(config)
    return _client
