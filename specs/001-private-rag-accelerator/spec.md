# Feature Specification: Private End-to-End RAG Accelerator

**Feature Branch**: `001-private-rag-accelerator`
**Created**: 2026-05-08
**Status**: Draft
**Input**: User description: "The goal of this project is to build a fully working end-to-end custom Azure solution that is completely private, making it easy to set [up]. This RAG solution should be... completely modernized, with all the latest semantic features for indexing. Complex documents, including PDFs, plain text, and images, need [to be supported]. The application must have RAG capabilities to process these documents smartly. Come up with a solution that keeps all of this in mind, and I need the UI to be sleek, preferably classic UI design — modern, sleek, and professional."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - End user asks questions and gets grounded answers with citations (Priority: P1)

A SLED knowledge worker (e.g., case worker, clinician, district staff member) signs in to a web chat experience hosted entirely on the customer's private network. They type a natural-language question about policy, procedure, or a specific case file. The assistant returns an answer grounded in the customer's own documents, with citations that link back to the exact source passages. The worker can refine the question conversationally and trust that no question, document, or answer ever traversed the public internet.

**Why this priority**: This is the primary value proposition of the accelerator. Without it, the deployment is just infrastructure with nothing to show. It also exercises every privacy boundary end-to-end (network, identity, data plane, model plane), which is the differentiating story for SLED customers.

**Independent Test**: With a pre-loaded sample corpus (handful of PDFs, text files, and images) and a single signed-in user, ask a question whose answer is in one of the documents. The assistant returns a correct answer in one or more sentences and shows at least one citation pointing to the source document and the relevant passage. Confirm via network traces that no traffic leaves the private virtual network during the request.

**Acceptance Scenarios**:

1. **Given** a signed-in user and an indexed sample corpus, **When** the user asks a question whose answer is contained in a single document, **Then** the assistant returns an answer that includes the correct fact and at least one citation linking to that document.
2. **Given** a signed-in user, **When** the user asks a follow-up question that depends on the prior turn (e.g., "and what about for minors?"), **Then** the assistant uses the conversation context and returns a coherent, grounded answer.
3. **Given** a signed-in user, **When** the user asks a question whose answer is NOT in the corpus, **Then** the assistant explicitly says it does not have that information rather than fabricating an answer.
4. **Given** an authenticated session, **When** any request is made (chat, citation fetch, document download), **Then** packet-level inspection shows zero traffic to public Azure or third-party endpoints; all traffic stays inside the deployed virtual network.

---

### User Story 2 - Administrator ingests a mixed-format document corpus (Priority: P1)

A customer administrator (or the deploying Solution Engineer) prepares the knowledge base by placing source documents (PDFs, plain-text files, Office documents, and images such as scanned forms or diagrams) into a designated private storage location. The accelerator detects new and changed files, extracts their text and visual content, generates semantic embeddings, and makes them searchable through the chat UI — without the admin having to write any code or manually invoke separate tools.

**Why this priority**: A RAG demo with no documents is not a demo. This story unblocks Story 1 and is the second thing every SE will exercise during a customer pilot. It also proves the "complex documents including PDFs, plain text, and images" requirement.

**Independent Test**: An admin drops a folder containing at least one PDF (with text and embedded images), one plain-text file, and one image file (e.g., a scanned form) into the designated ingestion location. Within a bounded time window, the documents appear as searchable in the chat UI and a status view shows each file as successfully indexed with no errors.

**Acceptance Scenarios**:

1. **Given** an empty corpus, **When** the admin uploads a folder containing PDF, TXT, DOCX, and PNG/JPG files, **Then** all files are processed and become available to chat queries within a documented time window.
2. **Given** a PDF that contains both typed text and an embedded scanned page, **When** the file is ingested, **Then** content from both the text layer and the scanned image is searchable.
3. **Given** an image file with text content (e.g., a screenshot of a form), **When** the file is ingested, **Then** the text extracted from the image is searchable and the original image is retrievable as the citation source.
4. **Given** a previously ingested document is deleted from the source location, **When** the next ingestion cycle runs, **Then** that document's content is removed from the searchable index and no longer appears in chat answers.
5. **Given** a corrupt or unsupported file, **When** ingestion runs, **Then** the file is skipped, the failure is recorded with a clear reason, and the rest of the batch completes successfully.

---

### User Story 3 - Solution Engineer deploys the accelerator into a customer subscription (Priority: P1)

A Microsoft Solution Engineer with appropriate Azure rights in a customer subscription clones the repository, sets a small number of parameters (subscription, resource group, region, naming prefix), and runs a single documented command. The full private RAG environment — network, identity, data, AI, and UI — is provisioned in a single deployment, with no manual portal steps required and no public endpoints created.

**Why this priority**: "Easy to set up" is an explicit requirement and the operational reason this is an *accelerator* rather than reference documentation. Without this story, every SE engagement is bespoke and the accelerator does not scale.

**Independent Test**: Starting from an empty resource group in a fresh subscription, an SE follows the documented quick-start. Within a documented time window, the deployment completes successfully, the chat UI is reachable from a connected client (e.g., via Azure Bastion or an existing VPN), and a smoke-test question against a seeded sample corpus returns a grounded answer.

**Acceptance Scenarios**:

1. **Given** an empty resource group, valid Azure credentials with Contributor + User Access Administrator on the scope, and the documented prerequisites installed, **When** the SE runs the documented one-command deployment, **Then** the deployment completes successfully and reports the URL of the chat UI.
2. **Given** a fresh deployment, **When** any deployed PaaS resource is inspected, **Then** its public network access is disabled and access is gated by a Private Endpoint inside the deployed virtual network.
3. **Given** a successful deployment, **When** the SE re-runs the same command with the same parameters, **Then** the run completes without errors and reports no resource changes (idempotent).
4. **Given** a successful deployment, **When** the SE runs the documented teardown command, **Then** all created resources are removed and no orphaned resources remain in the target scope.

---

### User Story 4 - Solution Engineer demonstrates the security posture to a customer architect (Priority: P2)

During a customer review, the SE walks the customer's security architect through the deployed environment. They show that every PaaS service has its public endpoint disabled, every cross-resource call uses managed identity, every Private Endpoint resolves through the customer's private DNS, and the chat UI itself is not reachable from the public internet.

**Why this priority**: SLED procurement and security teams gate purchases on this conversation. The accelerator must make this story easy to tell, not require post-deployment hardening.

**Independent Test**: From outside the customer's network, attempt to reach the chat UI's hostname and any of the deployed PaaS endpoints. All attempts fail (DNS resolves but connection refused, or DNS does not resolve publicly). From inside the deployed network, the same hostnames resolve to private IP addresses and connections succeed.

**Acceptance Scenarios**:

1. **Given** a deployed environment, **When** an external client resolves any deployed PaaS hostname, **Then** the resolution either fails or returns a public address that refuses connections.
2. **Given** a deployed environment, **When** a client inside the virtual network resolves a deployed PaaS hostname, **Then** it resolves to an address inside the documented private endpoint subnet range.
3. **Given** the deployed application, **When** its identity model is inspected, **Then** no shared keys, connection strings, or static credentials are present; all service-to-service calls use managed identity with documented least-privilege roles.

---

### User Story 5 - End user reviews and trusts a citation (Priority: P2)

A signed-in user reads an answer and clicks a citation. The original source passage opens in context (with the surrounding paragraph or page visible), so the user can verify the answer themselves before acting on it.

**Why this priority**: SLED users (clinicians, case workers, regulators) cannot act on AI output without a verifiable source. Citations are table-stakes for trust, but the *quality* of the citation experience is what differentiates a usable assistant from a toy.

**Independent Test**: For an answer that includes a citation, click the citation. The source document opens with the cited passage clearly identified (highlighted, scrolled to, or otherwise visually distinguished) within an acceptable load time.

**Acceptance Scenarios**:

1. **Given** an answer with one or more citations, **When** the user clicks a citation, **Then** the source document opens with the cited passage visually distinguished.
2. **Given** a citation that points to a passage on page N of a multi-page PDF, **When** the user clicks it, **Then** the document opens scrolled to (or paginated to) page N.
3. **Given** a citation that points to text extracted from an image, **When** the user clicks it, **Then** the original image is shown alongside the extracted text used to ground the answer.

---

### User Story 6 - Administrator monitors usage, ingestion health, and grounding quality (Priority: P3)

An administrator views a dashboard that shows: how many documents are indexed, the most recent ingestion run and its outcome, the number of questions asked, the share of questions the assistant declined to answer ("don't know"), and signals about answer quality (e.g., user thumbs-up/down).

**Why this priority**: Useful for pilots and sustained operation, but not required for the first SE-led demo. Adding it after the P1 stories are stable does not block the accelerator's primary value.

**Independent Test**: After a small set of ingestion runs and chat sessions, the dashboard reflects accurate counts and statuses.

**Acceptance Scenarios**:

1. **Given** completed ingestion runs and chat sessions, **When** the admin opens the dashboard, **Then** counts of indexed documents, recent runs, and chat sessions are accurate within a documented refresh window.
2. **Given** the assistant declined to answer a question, **When** the admin views the dashboard, **Then** that decline is reflected in the "don't know" rate.

---

### Edge Cases

- **End-user upload of a very large or sensitive document**: The system MUST enforce a documented per-upload size and per-user storage cap; uploads exceeding the cap MUST be rejected with a clear message rather than silently truncated. Content-safety screening (e.g., for malware-shaped payloads) MUST apply equally to user uploads and admin-curated content.
- **End user deletes a conversation that referenced an uploaded document**: The user-scoped Document and its Passages MUST be purged with the conversation; subsequent retrieval MUST not return them.
- **Very large document**: A single PDF substantially larger than the typical demo size (e.g., a 500-page regulation). The system MUST either ingest it successfully within a documented bound or skip it and report a clear reason; partial silent ingestion is unacceptable.
- **Document in an unsupported language or encoding**: The system MUST either index what it can or skip with a clear reason; it MUST NOT crash the ingestion batch.
- **Chat question containing PII or sensitive content**: Per SLED defaults the system MUST avoid logging raw question text in cleartext to long-lived telemetry; aggregated metrics only.
- **Identity provider outage**: If the identity provider is unreachable, the chat UI MUST refuse new sign-ins with a clear message and MUST NOT fall back to anonymous access.
- **Embedding or chat model rate-limit / temporary failure**: A single user request MUST be retried within a bounded budget; on persistent failure the user sees a clear, non-technical error and the request is logged for the admin.
- **Citation source no longer available** (document deleted between answer time and citation click): The user MUST see a clear "this source has been removed from the corpus" message rather than a broken page.
- **Concurrent ingestion and query load**: Ongoing ingestion MUST NOT block end-user chat; chat answers may transiently exclude in-flight documents but MUST NOT error.
- **Browser environment without modern features**: The chat UI is targeted at current evergreen browsers; older browsers MAY display a clear unsupported-browser message.

## Requirements *(mandatory)*

### Functional Requirements

#### Privacy and Network Posture

- **FR-001**: The system MUST be deployable such that no data-plane traffic between any deployed component traverses the public internet.
- **FR-002**: The system MUST disable the public network endpoint of every PaaS dependency it provisions; access MUST be gated through Private Endpoints inside the deployed virtual network.
- **FR-003**: The system MUST authenticate every service-to-service call using managed identity and documented least-privilege role assignments; static keys, connection strings, or shared secrets MUST NOT be used at runtime.
- **FR-004**: The chat UI MUST NOT be exposed on a public hostname by default; reachability MUST require either being on the deployed virtual network, on a peered network, or connecting through a documented private access path.
- **FR-005**: The system MUST resolve every deployed PaaS hostname through Azure Private DNS to a private IP inside the deployed virtual network when accessed from inside that network.

#### Identity and Authorization

- **FR-006**: End users MUST be required to authenticate with the customer's enterprise identity provider before they can interact with the chat UI; anonymous access MUST NOT be available.
- **FR-007**: The system MUST allow an administrator to restrict access to a defined set of users or groups in the customer's identity directory.
- **FR-008**: The system MUST distinguish between an "end user" role (chat, view citations) and an "administrator" role (ingest documents, view dashboard); role assignment MUST be governed by directory group membership.

#### Document Ingestion and Indexing

- **FR-009**: The system MUST ingest documents in at least the following formats: PDF (text and image-bearing), plain text, common Office document formats, and common image formats (e.g., PNG, JPEG).
- **FR-010**: The system MUST extract text from images and image-bearing PDFs (optical character recognition or equivalent) and make that extracted text searchable.
- **FR-011**: The system MUST generate semantic representations of document content suitable for similarity-based retrieval, in addition to keyword search.
- **FR-012**: The system MUST detect new, changed, and removed documents in the designated ingestion location and update the searchable index accordingly, on a schedule and on demand.
- **FR-013**: The system MUST record per-document ingestion outcome (success, skipped with reason, failed with reason) and surface this status to administrators.
- **FR-014**: The system MUST preserve a stable identifier for each ingested document so that citations remain resolvable as long as the document is in the corpus.

#### Retrieval and Generation (RAG)

- **FR-015**: For every chat question, the system MUST retrieve candidate passages from the indexed corpus using both semantic similarity and keyword matching, combined into a single ranked result set.
- **FR-016**: The system MUST ground generated answers in the retrieved passages and MUST include at least one citation per factual claim that originated from the corpus.
- **FR-017**: When the retrieved passages do not contain sufficient information to answer, the system MUST respond with an explicit "I don't have that information" style message rather than generating an unsupported answer.
- **FR-018**: The system MUST support multi-turn conversations in which a follow-up question can refer to entities or context from earlier turns within the same session.
- **FR-019**: The system MUST allow an administrator to configure (without code changes) the system prompt or grounding instructions used by the assistant.

#### User Interface

- **FR-020**: The system MUST present a single-page web chat experience with a modern, professional visual design — clean typography, generous whitespace, restrained color palette, accessible contrast, and a layout suitable for a SLED enterprise audience.
- **FR-021**: The chat UI MUST display, for each assistant turn, the answer text and a clearly distinguished list of citations.
- **FR-022**: The chat UI MUST allow the user to open a citation and view the cited passage in the context of its source document, with the cited passage visually distinguished.
- **FR-023**: The chat UI MUST support keyboard navigation and meet accessibility expectations equivalent to WCAG 2.1 AA for the primary chat and citation flows.
- **FR-024**: The chat UI MUST work on the current evergreen versions of major desktop browsers; mobile browser support is a non-blocking nice-to-have for v1.

#### Operability and Cost

- **FR-025**: The system MUST be deployable end-to-end via a documented one-command path using infrastructure-as-code, with no manual portal steps required on the supported path.
- **FR-026**: The deployment MUST be idempotent: re-running with the same parameters MUST complete cleanly and produce no drift.
- **FR-027**: The system MUST provide a documented teardown path that removes all created resources cleanly.
- **FR-028**: The default deployment MUST use the lowest-cost SKUs that demonstrate the capability, per the constitution's cost-discipline principle; production-grade SKUs MUST be opt-in parameters with documented cost impact.
- **FR-029**: The system MUST emit operational telemetry (deployment outcome, ingestion outcome, request counts, error counts, latency percentiles) to the customer's tenant, retrievable by an administrator without external services.

#### Conversation History and User Document Upload

- **FR-030**: The system MUST persist end-user conversation history on a per-user basis with a 30-day rolling retention window. Conversations older than 30 days from the user's last activity on that conversation MUST be automatically and irrecoverably purged. Users MUST be able to view their prior conversations on sign-in and MUST be able to delete any conversation (or all conversations) on demand, with deletion taking effect within a documented bounded time window.
- **FR-030a**: Conversation history MUST be stored in a tenant-isolated, customer-owned data store reachable only via Private Endpoint, encrypted at rest, and accessible only to the owning user's identity (and to administrators acting under a documented audit-logged code path); cross-user read access MUST NOT be possible through the application.
- **FR-031**: The system MUST allow end users to upload their own documents (at minimum: PDF, plain text, common Office formats, common image formats) through the chat UI for ad-hoc grounding within the current chat session. Such user-uploaded documents:
  - MUST be processed and made available for grounding in the user's current chat session,
  - MUST NOT be added to the administrator-curated shared corpus or made discoverable by any other user,
  - MUST be isolated to the uploading user's identity at the storage and index layers,
  - MUST be retained on the same 30-day rolling window as the conversation that created them, and MUST be purged when the parent conversation is purged or deleted,
  - MUST be subject to the same per-document size, format, and content-safety constraints as the administrator-curated corpus.
- **FR-031a**: The administrator-curated shared corpus and the per-user upload corpus MUST be queryable together within a single chat turn, with citations clearly distinguishing the source ("shared" vs "your upload").

### Key Entities

- **Document**: A source artifact (PDF, text file, Office document, image). Has a stable identifier, a source location, a **scope** (`shared` for the administrator-curated corpus, or `user:<userId>` for an end-user upload), an ingestion status, an ingestion timestamp, an extracted-content representation suitable for retrieval, and zero or more derived passages.
- **Passage**: A bounded chunk of extracted content from a Document, associated with a stable pointer back to the Document and the location within it (page, region, byte range). Used as the unit of retrieval and citation. Inherits the scope of its parent Document.
- **Citation**: A reference attached to part of an assistant answer, identifying one or more Passages and (transitively) their Documents. Surfaces the source scope ("shared corpus" vs "your upload") to the end user.
- **Conversation**: An ordered series of turns between one end user and the assistant. Owned by a single User, persisted with a 30-day rolling retention window (purged 30 days after the last activity on the conversation, or on user-initiated deletion). Each turn has a user message, an assistant response, and zero or more Citations. May reference zero or more user-uploaded Documents that are scoped to this Conversation.
- **User**: An authenticated principal from the customer's identity directory. Has a role (end user or administrator) and a set of permissions derived from group membership. Owns zero or more Conversations and zero or more user-scoped Documents.
- **Ingestion Run**: A discrete cycle of detecting and processing changes in the source location for the **shared** corpus. Has a start time, an end time, and per-Document outcomes. End-user uploads are processed inline in response to upload events, not via Ingestion Runs.
- **Index**: The searchable representation of currently-ingested Documents and Passages, supporting both semantic and keyword retrieval. Logically partitioned so that a query executed on behalf of a User retrieves from `shared` plus `user:<thatUserId>` and never from another user's scope.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A first-time Solution Engineer, following only the published quick-start, can take an empty resource group to a working chat UI answering a seeded sample question in under 60 minutes of wall-clock time, of which under 15 minutes is hands-on activity.
- **SC-002**: A re-run of the same deployment with the same parameters completes with zero resource changes (drift-free) in 100% of attempts on a clean subscription.
- **SC-003**: A documented teardown removes 100% of created resources in the target scope and leaves no orphaned resources, in 100% of attempts.
- **SC-004**: Independent inspection from outside the deployed virtual network confirms that 0 deployed PaaS endpoints accept public connections, in every supported deployment configuration.
- **SC-005**: For a seeded mixed-format corpus (containing at least one PDF with embedded scanned content, one plain-text file, and one image with text), 100% of files are either successfully ingested or surfaced to the administrator with a clear failure reason within one ingestion cycle.
- **SC-006**: For a curated benchmark question set whose answers are known to be in the seeded corpus, the assistant returns a grounded answer with at least one correct citation for at least 85% of questions, and explicitly declines to answer when the corpus does not contain the answer in at least 90% of out-of-scope questions.
- **SC-007**: 95% of chat responses (excluding model cold-start) complete in under 6 seconds end-to-end on the default demo SKUs.
- **SC-008**: A user opening a citation sees the cited passage visually distinguished within 2 seconds for typical demo-sized documents.
- **SC-009**: The default deployment's estimated steady-state cost (idle, no traffic) is published in the repository and is at most a documented monthly figure suitable for SE demo budgets; a deviation from the published figure of more than 20% triggers a constitution-required review of the SKU defaults.
- **SC-010**: Customer security architects reviewing the deployment can verify the security posture (FR-001 through FR-005) using only artifacts and views shipped with the accelerator, in under 30 minutes.
- **SC-011**: For every chat turn, retrieval scoped to User A MUST never return Passages owned by User B; this isolation property MUST hold in 100% of automated isolation tests across the supported deployment configurations.
- **SC-012**: Conversations and their associated user-scoped Documents MUST be purged within 24 hours of their 30-day expiry (or within 1 hour of user-initiated deletion), in 100% of automated retention tests.

## Assumptions

- The accelerator is deployed into a single Azure subscription per customer instance; multi-subscription / hub-and-spoke topologies are explicit future extensions, not the default path (per the constitution's Solution Accelerator Constraints).
- The customer's enterprise identity provider is Microsoft Entra ID; non-Entra identity providers are out of scope for v1.
- The customer provides a route from authorized end users to the deployed virtual network (existing VPN, ExpressRoute, peered network, or Azure Bastion / managed virtual desktop). Provisioning that route is out of scope for the accelerator itself.
- Document content is in English; multilingual support may work opportunistically but is not a v1 guarantee.
- Document volumes for the default demo configuration are on the order of hundreds of documents and tens of thousands of passages; production scale-up SKUs are an opt-in parameter set.
- The default ingestion source location for the **shared** corpus is a private storage location provisioned by the accelerator. Direct integration with external content systems (e.g., SharePoint Online, third-party DMS) is out of scope for v1.
- Conversation history and user-scoped uploaded documents are persisted in a customer-owned, tenant-isolated document database (Cosmos DB is the recommended store), reachable only via Private Endpoint, encrypted at rest with a customer-managed key where the customer requests it. Conversation transcripts and ingestion telemetry remain inside the customer's tenant; no telemetry is sent to Microsoft or any third party from the deployed application.
- The chat UI is desktop-web first; native mobile applications are out of scope for v1.
- "Classic, modern, sleek, professional" UI is interpreted as a restrained enterprise design system (clean typography, neutral palette with one accent color, generous whitespace, accessible contrast). A specific brand system (e.g., a customer's design tokens) is an opt-in customization, not the default.
- The accelerator is positioned as a starting point for HIPAA / FERPA / CJIS / IRS Pub. 1075 / FedRAMP Moderate alignment; it is not itself certified, per the constitution.

## Out of Scope (v1)

The following are explicitly excluded from v1 and SHOULD be tracked as candidate follow-up features:

- Multi-tenant isolation within a single deployment (per-department or per-agency segregation inside one environment).
- Automatic synchronization from external content sources (SharePoint Online, OneDrive, third-party document management systems, ticketing systems).
- Native mobile or offline clients.
- Multilingual answer generation as a guaranteed capability.
- Sovereign cloud (Gov, China) parameter sets — opt-in extensions, not the default path.
- End-user fine-tuning or model customization beyond administrator-editable system prompts.
- Conversational voice input/output.
