import logging

from tavily import AsyncTavilyClient

from core.agent_definition import SearchConfig
from core.models import SourceData
from utils.logger import get_logger

logger = get_logger(__name__)


class TavilySearchService:
    def __init__(self, search_config: SearchConfig):
        self._client = AsyncTavilyClient(
            api_key=search_config.tavily_api_key, api_base_url=search_config.tavily_api_base_url
        )
        self._config = search_config

    @staticmethod
    def rearrange_sources(sources: list[SourceData], starting_number=1) -> list[SourceData]:
        for i, source in enumerate(sources, starting_number):
            source.number = i
        return sources

    async def search(
        self,
        query: str,
        max_results: int | None = None,
        include_raw_content: bool = True,
    ) -> list[SourceData]:
        max_results = max_results or self._config.max_results
        logger.info(f"🔍 Tavily search: '{query}' (max_results={max_results})")

        response = await self._client.search(
            query=query,
            max_results=max_results,
            include_raw_content=include_raw_content,
        )

        sources = self._convert_to_source_data(response)
        return sources

    async def extract(self, urls: list[str]) -> list[SourceData]:
        logger.info(f"📄 Tavily extract: {len(urls)} URLs")

        response = await self._client.extract(urls=urls)

        sources = []
        for i, result in enumerate(response.get("results", [])):
            if not result.get("url"):
                continue

            source = SourceData(
                number=i,
                title=result.get("url", "").split("/")[-1] or "Extracted Content",
                url=result.get("url", ""),
                snippet="",
                full_content=result.get("raw_content", ""),
                char_count=len(result.get("raw_content", "")),
            )
            sources.append(source)

        failed_urls = response.get("failed_results", [])
        if failed_urls:
            logger.warning(f"⚠️ Failed to extract {len(failed_urls)} URLs: {failed_urls}")

        return sources

    def _convert_to_source_data(self, response: dict) -> list[SourceData]:
        sources = []

        for i, result in enumerate(response.get("results", [])):
            if not result.get("url", ""):
                continue

            source = SourceData(
                number=i,
                title=result.get("title", ""),
                url=result.get("url", ""),
                snippet=result.get("content", ""),
            )
            if result.get("raw_content", ""):
                source.full_content = result["raw_content"]
                source.char_count = len(source.full_content)
            sources.append(source)
        return sources
