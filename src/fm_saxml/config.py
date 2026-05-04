"""Configuration model for fm-saxml."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class MarkdownConfig(BaseModel):
    include_front_matter: bool = True
    include_backlinks: bool = True
    include_json_files: bool = True

    model_config = ConfigDict(populate_by_name=True)


class AnalysisConfig(BaseModel):
    parse_calculations: bool = True
    parse_script_step_text: bool = True
    include_unused_field_warnings: bool = True

    model_config = ConfigDict(populate_by_name=True)


class Config(BaseModel):
    project_name: Optional[str] = None
    input_file: Optional[Path] = None
    model_out: Optional[Path] = Field(None)
    markdown_out: Optional[Path] = Field(None)
    markdown: MarkdownConfig = Field(default_factory=MarkdownConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)

    model_config = ConfigDict(populate_by_name=True)
