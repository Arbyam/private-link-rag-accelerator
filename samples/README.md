# Sample Documents for Private RAG Accelerator Demo

This directory contains 5 sample documents used to populate the `shared-corpus` container during postprovisioning. These documents are ingested and indexed by the Azure AI Search service, enabling semantic search and retrieval-augmented generation (RAG) in the demo application.

## Files

### 1. private-link-overview.pdf
- **Type**: Multi-page PDF
- **Pages**: 3 (2 text pages + 1 OCR/scanned page)
- **Content**: Azure Private Link concepts, benefits, and technical architecture
- **Purpose**: Exercises text extraction via PyPDF2 and OCR via Document Intelligence on scanned content
- **Size**: ~50 KB

### 2. rag-architecture-notes.txt
- **Type**: Plain text file
- **Content**: Comprehensive guide to Retrieval-Augmented Generation fundamentals
- **Topics**: Document corpus, chunking, embeddings, vector storage, retrieval systems, prompt engineering
- **Purpose**: Provides domain knowledge about RAG for semantic search queries
- **Size**: ~8 KB

### 3. ai-search-deployment-guide.docx
- **Type**: Microsoft Word document
- **Content**: Step-by-step Azure AI Search deployment and configuration guide
- **Sections**: Introduction, deployment overview, best practices, configuration, monitoring
- **Purpose**: Tests DOCX extraction and provides operational guidance
- **Size**: ~15 KB

### 4. network-diagram-with-labels.png
- **Type**: PNG image with rendered text labels
- **Content**: Azure network architecture diagram showing VNet, subnets, private endpoints, NSGs
- **Dimensions**: 1000x800 pixels
- **Purpose**: Exercises OCR on image text and provides visual reference for network design
- **Size**: ~50 KB

### 5. cost-summary-chart.jpg
- **Type**: JPEG image with rendered text and chart
- **Content**: Azure service cost breakdown showing monthly costs by service type
- **Dimensions**: 1000x800 pixels
- **Purpose**: Demonstrates cost analysis and OCR on chart-style images
- **Size**: ~40 KB

## Generation

All files are generated deterministically using a Python script. To regenerate:

```bash
cd samples/
python generate.py
```

### Dependencies

The generation script requires:
- `reportlab` - PDF generation with text rendering
- `python-docx` - DOCX document creation
- `Pillow` - Image creation and manipulation

Install with:
```bash
pip install reportlab python-docx Pillow
```

## Content Relevance

All documents contain real, substantive content about Azure Private Link, RAG architecture, and AI Search deployment. This ensures the demo can:
- Perform meaningful semantic search (queries about "Azure Private Link" or "RAG architecture" will retrieve relevant documents)
- Demonstrate chunking and embedding across multiple document types
- Show accurate citation of sources in RAG responses
- Validate OCR pipeline for scanned content

## Integration

These files are automatically picked up by `scripts/postprovision.ps1` which:
1. Discovers files in the `samples/` directory
2. Filters by allowed MIME types (PDF, TXT, DOCX, PNG, JPEG)
3. Uploads up to 5 files to the `shared-corpus` Azure Blob Storage container
4. Triggers indexing pipeline to process and chunk documents for semantic search

See `scripts/postprovision.ps1` lines 186–246 for implementation details.
