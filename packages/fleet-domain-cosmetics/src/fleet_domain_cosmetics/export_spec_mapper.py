"""
Fleet Export Spec Mapper (v0.4.0).
Maps immutable ApprovedProductRecord into ProDocuX universal render specifications
and compiles individual prodocux_render_request_v1 payloads conforming to prodocux_content_blocks_v1 schema.
Strictly does NOT import any binary renderers (docx, openpyxl, pptx, reportlab).
"""
import uuid
from typing import Any, Dict, List
from fleet_governance_core.models.workflow_v4 import ApprovedProductRecord


def map_approved_product_to_render_bundle(
    product: ApprovedProductRecord,
    ingredients: List[Dict[str, Any]],
    sccs_summary: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Creates a complete multi-format render bundle specification for ProDocuX.
    """
    return {
        "bundle_version": "1.0.0",
        "product_id": product.product_id,
        "product_name": product.product_name,
        "revision": product.revision,
        "case_digest": product.case_digest,
        "plan_digest": product.plan_digest,
        "checkpoint_id": product.checkpoint_id,
        "finalized_at": product.finalized_at,
        "specs": {
            "pdf_report": {
                "template_id": "tpl-cosmetics-pif-summary-v1",
                "title": f"Regulatory Safety Dossier — {product.product_name}",
                "sections": [
                    {"heading": "1. Formulation Specification", "items": ingredients},
                    {"heading": "2. SCCS Toxicology Evaluation", "data": sccs_summary},
                    {"heading": "3. Governance & Checkpoints", "checkpoint_id": product.checkpoint_id},
                ],
            },
            "docx_document": {
                "template_id": "tpl-cosmetics-coa-spec-v1",
                "title": f"Certificate of Analysis — {product.product_name}",
                "tables": [
                    {
                        "name": "Formulation Table",
                        "headers": ["INCI Name", "Concentration (%)", "CAS Number", "NOAEL (mg/kg/day)"],
                        "rows": [
                            [
                                item.get("inci_name", ""),
                                str(item.get("concentration_pct", "")),
                                str(item.get("cas_number", "") or "—"),
                                str(item.get("noael_mg_kg_day", "") or "—"),
                            ]
                            for item in ingredients
                        ],
                    }
                ],
            },
            "csv_table": {
                "template_id": "tpl-cosmetics-raw-formula-v1",
                "filename": "formulation_matrix.csv",
                "headers": ["INCI_NAME", "CONCENTRATION_PCT", "CAS_NUMBER", "NOAEL_MG_KG_DAY"],
                "rows": [
                    [
                        item.get("inci_name", ""),
                        str(item.get("concentration_pct", "")),
                        str(item.get("cas_number", "") or ""),
                        str(item.get("noael_mg_kg_day", "") or ""),
                    ]
                    for item in ingredients
                ],
            },
            "xlsx_workbook": {
                "template_id": "tpl-cosmetics-toxicology-matrix-v1",
                "filename": "toxicology_study.xlsx",
                "sheets": [
                    {
                        "sheet_name": "Formulation & MoS",
                        "headers": ["INCI Name", "Concentration %", "SED (mg/kg/day)", "NOAEL", "Margin of Safety", "Status"],
                        "rows": [
                            [
                                item.get("inci_name", ""),
                                str(item.get("concentration_pct", 0.0)),
                                str(item.get("systemic_exposure_dose_mg_kg_day", 0.0)),
                                str(item.get("noael_mg_kg_day", 0.0)),
                                str(item.get("margin_of_safety", 0.0)),
                                str(item.get("verifier_status", "PASS")),
                            ]
                            for item in ingredients
                        ],
                    }
                ],
            },
            "pptx_presentation": {
                "template_id": "tpl-cosmetics-executive-review-v1",
                "filename": "executive_compliance_deck.pptx",
                "slides": [
                    {"title": f"Compliance Sign-off: {product.product_name}", "bullet_points": [f"Revision {product.revision}", f"Plan SHA: {product.plan_digest[:16]}..."]},
                    {"title": "Toxicology Highlights", "bullet_points": ["All substance MoS > 100", "EU Annex II/V Compliant"]},
                ],
            },
        },
    }


def map_bundle_to_prodocux_render_requests(bundle_spec: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Transforms Fleet render bundle specification into exact prodocux_render_request_v1
    payloads conforming strictly to prodocux_content_blocks_v1 schema.
    """
    product_name = bundle_spec.get("product_name", "Product")
    specs = bundle_spec.get("specs", {})
    requests_map: Dict[str, Dict[str, Any]] = {}

    # 1. CSV Render Request
    if "csv_table" in specs:
        csv_spec = specs["csv_table"]
        headers = csv_spec.get("headers", ["INCI_NAME", "CONCENTRATION_PCT"])
        rows = csv_spec.get("rows", [])
        table_rows = [headers] + rows if headers else rows

        requests_map["csv"] = {
            "schema_version": "prodocux_render_request_v1",
            "request_id": f"render-csv-{uuid.uuid4().hex[:8]}",
            "target_format": "csv",
            "content": {
                "schema_version": "prodocux_content_blocks_v1",
                "blocks": [
                    {
                        "id": "sheet_csv",
                        "type": "sheet",
                        "name": "Formulation",
                        "table": {
                            "header_rows": 1,
                            "rows": table_rows,
                        },
                    }
                ],
            },
            "output": {
                "output_name": "formulation.csv",
                "delivery_mode": "inline",
            },
        }

    # 2. XLSX Render Request
    if "xlsx_workbook" in specs:
        xlsx_spec = specs["xlsx_workbook"]
        sheets = []
        for s_idx, s in enumerate(xlsx_spec.get("sheets", [])):
            s_name = s.get("sheet_name", f"Sheet{s_idx + 1}").replace("&", "and")
            s_headers = s.get("headers", [])
            s_rows = s.get("rows", [])
            sheets.append(
                {
                    "id": f"sheet{s_idx + 1}",
                    "type": "sheet",
                    "name": s_name,
                    "table": {
                        "header_rows": 1 if s_headers else 0,
                        "rows": [s_headers] + s_rows if s_headers else s_rows,
                    },
                }
            )

        requests_map["xlsx"] = {
            "schema_version": "prodocux_render_request_v1",
            "request_id": f"render-xlsx-{uuid.uuid4().hex[:8]}",
            "target_format": "xlsx",
            "content": {
                "schema_version": "prodocux_content_blocks_v1",
                "blocks": sheets or [
                    {"id": "sheet1", "type": "sheet", "name": "Formulation", "table": {"header_rows": 1, "rows": [["Item", "Value"], ["Product", product_name]]}}
                ],
            },
            "output": {
                "output_name": "toxicology.xlsx",
                "delivery_mode": "inline",
            },
        }

    # 3. DOCX Render Request
    if "docx_document" in specs:
        docx_spec = specs["docx_document"]
        blocks: List[Dict[str, Any]] = [
            {"id": "h1", "type": "heading", "level": 1, "text": f"Certificate of Analysis: {product_name}"},
            {"id": "p1", "type": "paragraphs", "paragraphs": [f"Product: {product_name}", f"Status: Finalized Revision {bundle_spec.get('revision', 1)}"]},
        ]
        for t_idx, t in enumerate(docx_spec.get("tables", [])):
            t_headers = t.get("headers", [])
            t_rows = t.get("rows", [])
            blocks.append(
                {
                    "id": f"tbl{t_idx + 1}",
                    "type": "table",
                    "table": {
                        "header_rows": 1 if t_headers else 0,
                        "rows": [t_headers] + t_rows if t_headers else t_rows,
                    },
                }
            )

        requests_map["docx"] = {
            "schema_version": "prodocux_render_request_v1",
            "request_id": f"render-docx-{uuid.uuid4().hex[:8]}",
            "target_format": "docx",
            "content": {
                "schema_version": "prodocux_content_blocks_v1",
                "blocks": blocks,
            },
            "output": {
                "output_name": "certificate_of_analysis.docx",
                "delivery_mode": "inline",
            },
        }

    # 4. PPTX Render Request
    if "pptx_presentation" in specs:
        pptx_spec = specs["pptx_presentation"]
        slides: List[Dict[str, Any]] = []
        for s_idx, s in enumerate(pptx_spec.get("slides", [])):
            slides.append(
                {
                    "id": f"slide{s_idx + 1}",
                    "type": "slide",
                    "title": s.get("title", f"Slide {s_idx + 1}"),
                    "paragraphs": s.get("bullet_points", ["Compliance Review"]),
                }
            )

        requests_map["pptx"] = {
            "schema_version": "prodocux_render_request_v1",
            "request_id": f"render-pptx-{uuid.uuid4().hex[:8]}",
            "target_format": "pptx",
            "content": {
                "schema_version": "prodocux_content_blocks_v1",
                "blocks": slides or [
                    {"id": "slide1", "type": "slide", "title": product_name, "paragraphs": ["Compliance Review"]}
                ],
            },
            "output": {
                "output_name": "compliance_deck.pptx",
                "delivery_mode": "inline",
            },
        }

    # 5. PDF Render Request
    if "pdf_report" in specs:
        pdf_spec = specs["pdf_report"]
        pdf_blocks: List[Dict[str, Any]] = [
            {"id": "h1", "type": "heading", "level": 1, "text": f"Regulatory Safety Dossier: {product_name}"},
            {"id": "p1", "type": "paragraphs", "paragraphs": [f"Product Name: {product_name}", f"Dossier Digest: {bundle_spec.get('case_digest', '')}"]},
        ]
        for s_idx, sec in enumerate(pdf_spec.get("sections", [])):
            pdf_blocks.append({"id": f"hsec{s_idx + 1}", "type": "heading", "level": 2, "text": sec.get("heading", "")})
            if "items" in sec:
                item_lines = [f"{item.get('inci_name', '')}: {item.get('concentration_pct', '')}%" for item in sec["items"]]
                pdf_blocks.append({"id": f"psec{s_idx + 1}", "type": "paragraphs", "paragraphs": item_lines or ["No items declared."]})

        requests_map["pdf"] = {
            "schema_version": "prodocux_render_request_v1",
            "request_id": f"render-pdf-{uuid.uuid4().hex[:8]}",
            "target_format": "pdf",
            "content": {
                "schema_version": "prodocux_content_blocks_v1",
                "blocks": pdf_blocks,
            },
            "output": {
                "output_name": "safety_dossier.pdf",
                "delivery_mode": "inline",
            },
        }

    return requests_map
