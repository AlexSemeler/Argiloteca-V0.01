"""Factory that attaches modular DRX routes to the public blueprint.

The Argiloteca application already owns the public Flask blueprint named
``argiloteca``. Flask cannot register a second blueprint under the same name.
This factory therefore attaches dedicated DRX route modules to that existing
blueprint, preserving every ``argiloteca.<endpoint>`` contract.
"""

from dataclasses import dataclass
from typing import Any, Callable

from flask import Blueprint


@dataclass(frozen=True)
class DrxReadDependencies:
    render_template: Callable
    record_title_for_context: Callable
    authorized_mineral_catalog: Callable
    authorized_mineral_alias_map: Callable
    rag_client_factory: Callable
    list_records_with_drx: Callable
    list_raw_snapshot_items: Callable
    build_snapshot_suggestions: Callable
    load_diffractogram_data: Callable
    decimate_series: Callable
    build_technical_report_for_curve: Callable
    render_technical_report_html: Callable
    get_drx_run: Callable
    render_selection_report_html: Callable
    science_engine_status: Callable
    gsas2_status: Callable
    compare_completed_job: Callable
    search_reference_index: Callable
    neural_evidence_for_diffractogram: Callable
    list_external_jobs: Callable
    submit_external_job: Callable
    get_external_job: Callable
    list_drx_runs: Callable
    persist_drx_run: Callable
    record_exists: Callable
    import_raw_upload: Callable
    import_raw_path: Callable
    record_import_error: Callable
    external_curve_service_factory: Callable
    temp_upload_limit: Callable
    resolve_snapshot_raw_download: Callable | None = None


def create_drx_blueprint(public_blueprint: Blueprint, dependencies: DrxReadDependencies) -> Blueprint:
    """Register DRX read routes exactly once on the existing public blueprint."""
    if getattr(public_blueprint, "_argiloteca_drx_reads_registered", False):
        return public_blueprint
    from .comparison_routes import register_comparison_routes
    from .curve_routes import register_curve_routes
    from .rag_routes import register_rag_routes
    from .job_routes import register_job_routes
    from .reference_routes import register_reference_routes
    from .report_routes import register_report_routes
    from .run_routes import register_run_routes
    from .upload_routes import register_upload_routes

    register_comparison_routes(public_blueprint, dependencies)
    register_rag_routes(public_blueprint, dependencies)
    register_curve_routes(public_blueprint, dependencies)
    register_report_routes(public_blueprint, dependencies)
    register_reference_routes(public_blueprint, dependencies)
    register_job_routes(public_blueprint, dependencies)
    register_run_routes(public_blueprint, dependencies)
    register_upload_routes(public_blueprint, dependencies)
    public_blueprint._argiloteca_drx_reads_registered = True
    return public_blueprint
