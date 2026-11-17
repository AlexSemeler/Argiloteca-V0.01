from flask import g, request


def register_comparison_routes(blueprint, deps):
    @blueprint.route("/drx/comparacao", endpoint="drx_comparacao")
    def drx_comparacao():
        context_record_id = (request.args.get("record_id") or "").strip()
        from ...scientific.drx_links import PID, record_for, native_records_available
        context_record_title = (record_for(g.identity, context_record_id)._record['metadata']['title']
            if PID.fullmatch(context_record_id) and native_records_available() else
            deps.record_title_for_context(context_record_id) if context_record_id else None)
        catalog = deps.authorized_mineral_catalog()
        slugs = sorted({item.get("slug") for item in catalog if item.get("slug")})
        return deps.render_template(
            "semantic-ui/argiloteca/drx_comparacao.html",
            authorized_mineral_slugs=slugs,
            authorized_mineral_aliases=deps.authorized_mineral_alias_map(catalog),
            context_record_id=context_record_id,
            context_record_title=context_record_title or context_record_id,
            context_source=(request.args.get("source") or "").strip(),
        )
