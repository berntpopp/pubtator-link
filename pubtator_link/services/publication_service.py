"""Publication service with caching for PubTator-Link."""

import asyncio
from typing import Any, Dict, List, Optional

from async_lru import alru_cache
from structlog.typing import FilteringBoundLogger

from ..api.client import PubTator3Client, PubTatorAPIError
from ..config import cache_config
from ..logging_config import log_cache_event
from ..models.publications import (
    AnnotatedPublication,
    ExportFormat,
    EXPORT_FORMATS,
    PublicationBatch,
    PublicationMetadata,
)
from ..models.responses import (
    PMCExportResponse,
    PublicationExportResponse,
    SearchResponse,
    SearchResult,
)


class PublicationService:
    """Service for publication operations with caching."""

    def __init__(
        self, client: PubTator3Client, logger: Optional[FilteringBoundLogger] = None
    ):
        """Initialize publication service.

        Args:
            client: PubTator3 API client
            logger: Optional logger instance
        """
        self.client = client
        self.logger = logger

    @alru_cache(maxsize=cache_config.size, ttl=cache_config.ttl)
    async def export_publications(
        self, pmids_str: str, format: str = "biocjson", full: bool = False
    ) -> PublicationExportResponse:
        """Export publication annotations with caching.

        Args:
            pmids_str: Comma-separated PMIDs string for caching
            format: Export format
            full: Include full text

        Returns:
            Publication export response
        """
        # Parse pmids string back to list
        pmids = [pmid.strip() for pmid in pmids_str.split(",") if pmid.strip()]

        if self.logger:
            log_cache_event(
                self.logger,
                event="miss",
                cache_key=f"pub_export:{pmids_str}:{format}:{full}",
                hit=False,
            )

        try:
            raw_data = await self.client.export_publications(
                pmids=pmids, format=format, full=full
            )

            documents = self._parse_export_data(raw_data, format)

            return PublicationExportResponse(
                format=format,
                pmids=pmids,
                full_text=full,
                export_data={"documents": documents},
                count=len(documents),
            )

        except PubTatorAPIError as e:
            if self.logger:
                self.logger.error(
                    "Publication export failed",
                    pmids=pmids,
                    format=format,
                    error=str(e),
                )
            raise

    async def export_publications_list(
        self, pmids: List[str], format: str = "biocjson", full: bool = False
    ) -> PublicationExportResponse:
        """Export publications with list interface.

        Args:
            pmids: List of PubMed IDs
            format: Export format
            full: Include full text

        Returns:
            Publication export response
        """
        pmids_str = ",".join(pmids)
        return await self.export_publications(pmids_str, format, full)

    @alru_cache(maxsize=cache_config.size, ttl=cache_config.ttl)
    async def export_pmc_publications(
        self, pmcids_str: str, format: str = "biocjson"
    ) -> PMCExportResponse:
        """Export PMC publication annotations with caching.

        Args:
            pmcids_str: Comma-separated PMC IDs string for caching
            format: Export format

        Returns:
            PMC export response
        """
        # Parse pmcids string back to list
        pmcids = [pmcid.strip() for pmcid in pmcids_str.split(",") if pmcid.strip()]

        if self.logger:
            log_cache_event(
                self.logger,
                event="miss",
                cache_key=f"pmc_export:{pmcids_str}:{format}",
                hit=False,
            )

        try:
            raw_data = await self.client.export_pmc_publications(
                pmcids=pmcids, format=format
            )

            documents = self._parse_export_data(raw_data, format)

            return PMCExportResponse(
                documents=documents,
                format=format,
                pmcids=pmcids,
                total_documents=len(documents),
            )

        except PubTatorAPIError as e:
            if self.logger:
                self.logger.error(
                    "PMC export failed", pmcids=pmcids, format=format, error=str(e)
                )
            raise

    async def export_pmc_publications_list(
        self, pmcids: List[str], format: str = "biocjson"
    ) -> PMCExportResponse:
        """Export PMC publications with list interface.

        Args:
            pmcids: List of PMC IDs
            format: Export format

        Returns:
            PMC export response
        """
        pmcids_str = ",".join(pmcids)
        return await self.export_pmc_publications(pmcids_str, format)

    @alru_cache(maxsize=cache_config.size, ttl=cache_config.ttl)
    async def search_publications(self, text: str, page: int = 1) -> SearchResponse:
        """Search publications with caching.

        Args:
            text: Search query
            page: Page number

        Returns:
            Search response
        """
        if self.logger:
            log_cache_event(
                self.logger, event="miss", cache_key=f"search:{text}:{page}", hit=False
            )

        try:
            raw_data = await self.client.search_publications(text=text, page=page)
            return self._parse_search_results(raw_data, text, page)

        except PubTatorAPIError as e:
            if self.logger:
                self.logger.error(
                    "Publication search failed", query=text, page=page, error=str(e)
                )
            raise

    async def batch_export_publications(
        self,
        pmids: List[str],
        format: str = "biocjson",
        full: bool = False,
        batch_size: int = 50,
    ) -> PublicationBatch:
        """Export publications in batches for large requests.

        Args:
            pmids: List of PubMed IDs
            format: Export format
            full: Include full text
            batch_size: Number of PMIDs per batch

        Returns:
            Publication batch with all results
        """
        batch_id = f"batch_{int(asyncio.get_event_loop().time())}"
        batch = PublicationBatch(batch_id=batch_id, processing_status="processing")

        # Split PMIDs into batches
        pmid_batches = [
            pmids[i : i + batch_size] for i in range(0, len(pmids), batch_size)
        ]

        # Process batches concurrently
        tasks = [
            self.export_publications_list(batch_pmids, format, full)
            for batch_pmids in pmid_batches
        ]

        try:
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            all_documents = []
            for result in batch_results:
                if isinstance(result, Exception):
                    batch.error_count += 1
                    if self.logger:
                        self.logger.error(
                            "Batch export error", batch_id=batch_id, error=str(result)
                        )
                else:
                    batch.success_count += len(result.documents)
                    all_documents.extend(result.documents)

            # Create publications from documents
            publications = [self._document_to_publication(doc) for doc in all_documents]

            batch.publications = publications
            batch.processing_status = "completed"

            return batch

        except Exception as e:
            batch.processing_status = "failed"
            batch.error_count = len(pmid_batches)
            if self.logger:
                self.logger.error(
                    "Batch export failed completely", batch_id=batch_id, error=str(e)
                )
            raise

    def _parse_export_data(self, raw_data: Dict[str, Any], format: str) -> List[Any]:
        """Parse export data based on format.

        Args:
            raw_data: Raw API response
            format: Export format

        Returns:
            Parsed documents
        """
        content = raw_data.get("content", "")
        content_type = raw_data.get("content_type", "")

        if format == "biocjson":
            # BioC JSON format
            if isinstance(raw_data, dict):
                # Check for PubTator3 response format
                if "PubTator3" in raw_data:
                    return raw_data["PubTator3"]
                elif "documents" in raw_data:
                    return raw_data["documents"]
            elif content:
                try:
                    import json

                    parsed = json.loads(content)
                    if "PubTator3" in parsed:
                        return parsed["PubTator3"]
                    return parsed.get("documents", [parsed])
                except json.JSONDecodeError:
                    return [{"content": content, "format": format}]

        elif format == "biocxml":
            # BioC XML format
            return [
                {
                    "id": "biocxml_document",
                    "content": content,
                    "format": format,
                    "content_type": content_type,
                }
            ]

        elif format == "pubtator":
            # PubTator format - parse line by line
            lines = content.strip().split("\n")
            documents = []
            current_doc = None

            for line in lines:
                if not line.strip():
                    continue

                if "|t|" in line or "|a|" in line:
                    # Title or abstract line
                    if current_doc:
                        documents.append(current_doc)
                    parts = line.split("|")
                    pmid = parts[0]
                    section = parts[1]
                    text = "|".join(parts[2:]) if len(parts) > 2 else ""

                    current_doc = {
                        "pmid": pmid,
                        "sections": {section: text},
                        "annotations": [],
                    }
                else:
                    # Annotation line
                    if current_doc:
                        current_doc["annotations"].append(line)

            if current_doc:
                documents.append(current_doc)

            return documents

        return [{"content": content, "format": format}]

    def _parse_search_results(
        self, raw_data: Dict[str, Any], query: str, page: int
    ) -> SearchResponse:
        """Parse search results from API response.

        Args:
            raw_data: Raw API response
            query: Original query
            page: Page number

        Returns:
            Parsed search response
        """
        # Handle different response formats
        results = []
        total_results = 0
        per_page = 20

        if isinstance(raw_data, dict):
            # Structured response
            if "results" in raw_data:
                results_data = raw_data["results"]
            elif "documents" in raw_data:
                results_data = raw_data["documents"]
            else:
                results_data = [raw_data]

            total_results = raw_data.get("total", len(results_data))
            per_page = raw_data.get("per_page", 20)

            for item in results_data:
                result = SearchResult(
                    pmid=str(item.get("pmid", item.get("id", ""))),
                    title=item.get(
                        "title", item.get("passages", [{}])[0].get("text", "")
                    ),
                    abstract=self._extract_abstract(item),
                    authors=item.get("authors", []),
                    journal=item.get("journal", ""),
                    pub_date=item.get("date", item.get("pub_date", "")),
                    annotations=item.get("annotations", []),
                    score=item.get("score", item.get("relevance", None)),
                )
                results.append(result)

        total_pages = (total_results + per_page - 1) // per_page

        return SearchResponse(
            query=query,
            results=results,
            total_results=total_results,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
        )

    def _extract_abstract(self, item: Dict[str, Any]) -> Optional[str]:
        """Extract abstract text from different response formats."""
        # Try direct abstract field
        if "abstract" in item:
            return item["abstract"]

        # Try passages array
        passages = item.get("passages", [])
        for passage in passages:
            infons = passage.get("infons", {})
            if infons.get("section") == "abstract" or infons.get("type") == "abstract":
                return passage.get("text", "")

        return None

    def _document_to_publication(self, document: Any) -> AnnotatedPublication:
        """Convert document to AnnotatedPublication.

        Args:
            document: Document data

        Returns:
            AnnotatedPublication instance
        """
        # Extract basic metadata
        pmid = str(document.get("pmid", document.get("id", "")))

        metadata = PublicationMetadata(
            pmid=pmid,
            title=document.get("title", ""),
            abstract=self._extract_abstract(document),
        )

        # Create basic publication
        return AnnotatedPublication(
            metadata=metadata,
            passages=[],
            relations=[],
            annotation_metadata={"source": "pubtator3", "format": "unknown"},
        )

    def get_supported_formats(self) -> Dict[str, ExportFormat]:
        """Get supported export formats."""
        return EXPORT_FORMATS

    async def clear_cache(self, pattern: Optional[str] = None) -> int:
        """Clear cache entries.

        Args:
            pattern: Cache key pattern (not implemented in async-lru)

        Returns:
            Number of cleared entries (always returns cache size for full clear)
        """
        # async-lru doesn't support pattern-based clearing
        # This is a full cache clear
        cache_size = cache_config.size

        # Clear all cached methods
        self.export_publications.cache_clear()
        self.export_pmc_publications.cache_clear()
        self.search_publications.cache_clear()

        if self.logger:
            self.logger.info("Cache cleared", cleared_items=cache_size)

        return cache_size

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Cache statistics in expected format
        """
        # Get cache info from async-lru for each cached method
        export_info = self.export_publications.cache_info()
        pmc_info = self.export_pmc_publications.cache_info()
        search_info = self.search_publications.cache_info()

        # Calculate totals
        total_hits = export_info.hits + pmc_info.hits + search_info.hits
        total_misses = export_info.misses + pmc_info.misses + search_info.misses
        total_requests = total_hits + total_misses

        hit_rate = total_hits / total_requests if total_requests > 0 else 0.0
        miss_rate = total_misses / total_requests if total_requests > 0 else 0.0

        # Current size is the sum of current entries in all caches
        current_size = export_info.currsize + pmc_info.currsize + search_info.currsize

        basic_stats = {
            "total_size": cache_config.size * 3,  # 3 cached methods
            "current_size": current_size,
            "hit_rate": round(hit_rate, 3),
            "miss_rate": round(miss_rate, 3),
            "total_hits": total_hits,
            "total_misses": total_misses,
        }

        detailed_stats = {
            "publication_export": {
                "size": export_info.currsize,
                "hits": export_info.hits,
                "misses": export_info.misses,
                "hit_rate": (
                    round(export_info.hits / (export_info.hits + export_info.misses), 3)
                    if (export_info.hits + export_info.misses) > 0
                    else 0.0
                ),
            },
            "pmc_export": {
                "size": pmc_info.currsize,
                "hits": pmc_info.hits,
                "misses": pmc_info.misses,
                "hit_rate": (
                    round(pmc_info.hits / (pmc_info.hits + pmc_info.misses), 3)
                    if (pmc_info.hits + pmc_info.misses) > 0
                    else 0.0
                ),
            },
            "search": {
                "size": search_info.currsize,
                "hits": search_info.hits,
                "misses": search_info.misses,
                "hit_rate": (
                    round(search_info.hits / (search_info.hits + search_info.misses), 3)
                    if (search_info.hits + search_info.misses) > 0
                    else 0.0
                ),
            },
        }

        return {**basic_stats, "detailed_stats": detailed_stats}
