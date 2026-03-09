from __future__ import annotations

from app.tools.registry import ToolRegistry
from app.tools.filesystem import FileSystemTool
from app.tools.docgen import DocxGeneratorTool, PdfGeneratorTool
from app.tools.email_smtp import SmtpEmailTool
from app.tools.manual_linkedin import ManualLinkedInActionTool
from app.tools.http import HttpGetTool
from app.tools.rag import RagUpsertTool, RagQueryTool, RagDeleteDocumentTool, RagDeleteNamespaceTool
from app.tools.sheets import SheetsReadTool, SheetsAppendTool, SheetsUpdateTool, SheetsClearTool


def build_registry() -> ToolRegistry:
    reg = ToolRegistry(_tools={})
    reg.register(HttpGetTool())
    reg.register(FileSystemTool())
    reg.register(DocxGeneratorTool())
    reg.register(PdfGeneratorTool())
    reg.register(ManualLinkedInActionTool())
    reg.register(SmtpEmailTool())

    reg.register(RagUpsertTool())
    reg.register(RagQueryTool())
    reg.register(RagDeleteDocumentTool())
    reg.register(RagDeleteNamespaceTool())

    reg.register(SheetsReadTool())
    reg.register(SheetsAppendTool())
    reg.register(SheetsUpdateTool())
    reg.register(SheetsClearTool())

    return reg
