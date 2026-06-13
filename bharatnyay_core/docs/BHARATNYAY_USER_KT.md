# BharatNyay ODR Workspace — User Knowledge Transfer (KT)

This guide explains how to use the **BharatNyay** dispute-resolution workspace in Odoo 18: dashboards, case workflow, postal tracking (POD), billing, documents, and bulk operations.

**Audience:** Admin, Case Manager, Arbitrator, and billing operations staff.

---

## 1. What this system does

BharatNyay manages **loan / arbitration cases** from import through notices, hearings, award, postal delivery, and consolidated invoicing.

Each **case** (`Loan sheet`) moves through fixed **workflow stages** (milestones). Key parallel tracks:

| Track | Purpose |
|--------|---------|
| **Workflow** | Commencement → Notice 1–3 → Hearing 1–3 → Award |
| **Postal (POD)** | Tracking for **Notice 1**, **Hearing 1 (Interim Order 1)**, and **Award** documents |
| **Billing** | Unbilled charges accrue per rules below; admin creates **consolidated invoices** |
| **Case Vault** | Batch PDF packs (merged notices / documents per import batch) |

---

## 2. Roles and home screens

| Role | Home menu | What you see |
|------|-----------|--------------|
| **Admin** | **Admin Dashboard** | Full portfolio: KPIs, filters, bulk **Move to next stage**, Case Vault, jobs |
| **Case Manager** | **Case Manager** | Cases assigned to you; pipeline, POD, billing summary |
| **Arbitrator** | **Arbitrator** | Assigned hearings and awards |

Configure users under **Masters → User roles**. Case managers can be scoped to **branches / locations** so auto-assignment works when cases enter Notice 1.

---

## 3. Main menus (quick map)

```
BharatNyay
├── Admin Dashboard / Case Manager / Arbitrator   ← role dashboards
├── Cases                                         ← all loan sheets
├── Case Vault                                    ← batch document packs
├── Background processes                          ← long-running jobs (admin)
├── Workflow queues                               ← operational lists (admin)
├── Billing
│   ├── Unbilled charges
│   ├── Create consolidated invoice
│   ├── Import postal tracking                  ← Excel POD upload
│   └── Invoices
└── Masters
    ├── Geography (Regions, States, Locations, Branches)
    ├── Post office status                        ← POD status master (billable flags)
    ├── Products                                  ← one SKU per billable stage
    └── Milestones / stages                       ← workflow configuration
```

---

## 4. Case workflow (milestones)

Standard path (one step at a time):

```
Commencement → Notice 1 → Notice 2 → Notice 3 → Hearing 1 → Hearing 2 → Hearing 3 → Award
```

### What happens automatically on stage entry

| Entering stage | Typical automation |
|----------------|-------------------|
| **Notice 1** | Case manager auto-assigned (by branch/location scope) |
| **Hearing 1** | Arbitrator assignment rules; hearing lines |
| **Notice 1 / Hearing 1 / Award** | A **postal dispatch** row is created for POD tracking |
| **Award** | Draft award document; case may lock after certain POD statuses |

### Bulk advance (Admin dashboard)

**Move to next stage** advances **all filtered cases by exactly one milestone**.

A popup wizard asks (all **unchecked by default** for testing):

| Option | If checked |
|--------|------------|
| **Generate PDFs during advance** | Renders notice/hearing PDFs immediately (slow on large batches) |
| **Send email to borrower** | Sends notice email |
| **Send SMS to borrower** | Logs SMS on case chatter (gateway can be wired later) |

If all are unchecked: cases move only; PDFs/emails/SMS are skipped.

**Tip:** Use dashboard **filters** (region, state, batch) before bulk advance. Track progress under **Running jobs** on the dashboard.

---

## 5. Postal delivery (POD)

Three documents follow postal workflow:

| Document | Workflow link | Billing stage code |
|----------|---------------|-------------------|
| **Notice 1** | First legal notice | Notice 1 |
| **Interim Order 1** | First hearing / IO | Hearing 1 |
| **Award** | Final award dispatch | Award |

### Updating POD (two ways)

1. **Manual — Update POD**
   - From a **Notice 1** form: button **Update POD**
   - From case form: postal delivery cards → open status wizard
   - Enter: POD/tracking no., dispatch date, delivery date, **Post office status**

2. **Excel — Import postal tracking**
   - **Billing → Import postal tracking**
   - Or portfolio import with type **POD status**
   - Columns: case reference, document type, POD, dates, status text (must match master names)

### Post office status master

**Masters → Post office status**

Each status has flags:

| Flag | Meaning |
|------|---------|
| **Delivery confirmed** | Treats delivery as complete |
| **Accrue unbilled charge** | **Billable** — queues an unbilled charge when saved on a dispatch row |
| **Lock case** | Case becomes read-only (e.g. RRN locked) |

**Default billable statuses:** *Delivered*, *RRN locked*  
**Non-billable examples:** *Dispatched*, *In transit*, *POD received*, *Returned undelivered*

---

## 6. Billing and unbilled charges

### When charges accrue

| Stage / event | When charge is created |
|---------------|------------------------|
| **Notice 1, Hearing 1, Award** | **Only** when POD **post office status** is set to a **billable** status (Excel or manual POD update). **Not** when you bulk-move workflow stage. |
| **Notice 2, Notice 3, Hearing 2, Hearing 3** | When the case **leaves** that milestone (milestone exit) |

Each case can have **at most one pending charge per milestone code**.

### Admin dashboard — Unbilled charges pipeline

Below the KPI row you will see a left-to-right pipeline:

```
Notice 1  →  Hearing 1  →  Award  →  Total unbilled
```

Each box shows **amount**, **charge count**, **case count**, and share of total. **Click a box** to open the filtered **Unbilled charges** list.

The **Unbilled charges** KPI shows total **₹ amount** and charge/case counts.

### Creating invoices

1. Review **Billing → Unbilled charges** (filter: Pending).
2. Run **Billing → Create consolidated invoice** — select lender/batch as needed.
3. Posted invoices appear under **Billing → Invoices** and on dashboard invoice KPIs.

### Products and rates

**Masters → Products** — one arbitration billing product per stage (Notice 1, Notice 2, … Award). Rates feed unbilled charge amounts.

---

## 7. Notices and PDFs

Each notice sent creates a **notice line** (email history) on the case.

| Situation | PDF behaviour |
|-----------|----------------|
| Bulk advance **without** “Generate PDFs” | PDF is **deferred** — generated when you **open the notice form**, or via **Generate PDF** button |
| Bulk advance **with** Generate PDFs | PDF created during the job |
| **Case Vault** | Merged **batch** PDF packs — separate from per-notice PDF on the form |

**Do not** run mass PDF backfill on every module upgrade (it can hang the server). Generate on demand or in controlled batches.

---

## 8. Case Vault

**Case Vault** builds **batch document packs** (e.g. all Notice 1 PDFs for Batch 1).

- Shown on Admin dashboard under batch cards.
- **Ready** = pack built; use download actions on the vault batch.
- Rebuild is triggered after bulk operations (may run as background job).

Case Vault packs ≠ individual notice PDF on each notice line.

---

## 9. Importing cases (Excel)

Use **Upload new batch** on the dashboard or the portfolio import wizard.

Typical flow:

1. Import loan sheet → cases land in **Commencement** (or as configured).
2. Configure **case managers** with correct **branch/location** scope (or one unscoped CM as fallback).
3. **Move to next stage** to push portfolio toward Notice 1 / beyond.
4. Import or manually update **POD** when post office confirms delivery → **billable charges** accrue for N1 / H1 / Award.

**Import types** include: new cases, POD status, and other operational updates (see import wizard help text).

---

## 10. Dashboard KPIs (Admin) — cheat sheet

| KPI | Meaning |
|-----|---------|
| **Total cases / batches** | Portfolio size and import batches |
| **Running jobs** | Bulk milestone advance, Case Vault builds, etc. |
| **Awaiting POD status** | Dispatched but not yet on a billable post office status (Notice 1 / IO1 focus) |
| **Total / Paid / Unpaid invoices** | Arbitration invoice totals |
| **Unbilled charges** | Pending charges not yet invoiced |
| **Hearings today** | Hearings scheduled for today (user timezone) |

**Case pipeline** tiles = count per workflow stage (click to open filtered case list).  
**Postal delivery (POD)** tiles = pending vs done per document type (click to drill down).

---

## 11. Common issues and fixes

| Symptom | Likely cause | What to do |
|---------|--------------|------------|
| Cases stuck at **Commencement** after bulk move | No case manager for branch/location | **Masters → User roles** — widen CM branch/location scope; re-run move |
| **Unbilled charges** for N1/H1/Award but no POD update | Old data from before POD-only billing rule | Cancel incorrect pending rows or leave; new accruals need billable POD status |
| Notice PDF panel **empty** | PDF deferred after bulk move | Open notice once, or click **Generate PDF** |
| **Award – POD pending** list looked blank | Fixed: opens postal dispatch list with columns | Upgrade module; refresh browser |
| Upgrade **hangs** | Never run 500+ PDF backfill on upgrade | Upgrade without mass PDF data hooks; clear assets if UI breaks |
| **Style compilation failed** / white screen | Stale assets | Developer mode → **Clear assets**; hard refresh (Ctrl+Shift+R) |
| Bulk move “failed” cases | See **Background processes** job message | Often CM scope or validation — message lists case refs |

---

## 12. Admin maintenance checklist

After deploying code changes:

```bash
./odoo-bin -u bharatnyay_core -d <your_database>
```

Then (if UI issues):

1. Enable **Developer mode**
2. **Settings → Developer Tools → Clear assets**
3. Hard refresh browser

Verify:

- [ ] Milestones synced (**Masters**)
- [ ] Billing products exist for each stage
- [ ] Post office statuses have correct **Accrue unbilled charge** flags
- [ ] Case managers scoped to all active branches
- [ ] Test one case: POD update → unbilled charge appears → consolidated invoice

---

## 13. Glossary

| Term | Definition |
|------|------------|
| **Case / Loan sheet** | One dispute record (`bharat.loan`) |
| **Milestone / Stage** | Workflow step (Notice 1, Hearing 2, …) |
| **POD** | Proof of delivery / postal tracking number |
| **Postal dispatch** | One row tracking post for Notice 1, IO1, or Award |
| **Unbilled charge** | Pending billing event — not yet on an invoice |
| **Consolidated invoice** | One invoice covering many cases’ pending charges |
| **Case Vault** | Batch-level merged PDF archive |

---

## 14. Support contacts / escalation

Document your internal:

- **Odoo admin** (upgrades, assets, server)
- **Billing owner** (products, rates, invoice runs)
- **Operations lead** (POD imports, bulk stage moves)

For developers: module `bharatnyay_core`, database backups before bulk operations on production.

---

*Document version: aligned with `bharatnyay_core` 18.0.31.x — POD-gated billing for Notice 1 / Hearing 1 / Award, unbilled charges pipeline, milestone advance wizard.*
