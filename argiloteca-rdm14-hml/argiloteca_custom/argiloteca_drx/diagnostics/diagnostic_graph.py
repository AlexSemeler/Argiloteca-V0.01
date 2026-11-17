# =============================================================================
# Projeto...........: Argiloteca – Painel de DRX
# Módulo............: diagnostic_graph.py
#
# Descrição.........:
# Implementa regras, evidências e estruturas de interpretação mineralógica por DRX N/G/C.
#
# Autor.............:
# Alexandre Ribas Semeler
# alexandre.semeler@ufrgs.br
#
# Última atualização:
# 2026-06-25
#
# =============================================================================

"""Evidence graph representation.

Fundamentacao cientifica revisada:
    Este arquivo integra o Painel DRX da Argiloteca, projeto fundamentado nas
    referencias cientificas revisadas para interpretacao auxiliar de DRX de
    argilominerais: Brindley & Brown (1980), Bailey (1980/1988),
    Moore & Reynolds (1989/1997), Drits & Tchoubar (1990),
    Lanson & Bouchet (1995), Meunier, Clays (2005), fluxograma USGS para
    identificacao de argilominerais por DRX e referencias empiricas Pre-Sal
    UFRGS/Petrobras.

Autoria cientifica e curadoria:
    Alexandre Ribas Semeler
    E-mail: alexandre.semler@ufrgs.br

Politica de interpretacao:
    Resultados mineralogicos sao auxiliares e nao confirmatorios. O codigo
    combina comportamento N/G/C, picos companheiros, d060, ambiguidades,
    contexto e proveniencia; nao confirma mineral por pico isolado.
"""

from __future__ import annotations


def build_diagnostic_graph(relations, candidates=None):
    """
    Executa a etapa `build_diagnostic_graph` do módulo.

        Args:
            relations:
                Parâmetro utilizado pela etapa `build_diagnostic_graph`.
            candidates:
                Parâmetro utilizado pela etapa `build_diagnostic_graph`.
        Returns:
            Resultado documentado pelo contrato do chamador.

        Notes:
            Em fluxos DRX, valores de 2θ, d-spacing, FWHM e intensidade
            relativa devem ser interpretados em conjunto com preparação
            natural, glicolada e calcinada. Nenhum pico isolado deve ser
            tratado como confirmação mineralógica completa.
    """
    nodes = []
    seen = set()
    for prep in ("N", "G", "C"):
        nodes.append({"id": "preparation:%s" % prep, "type": "preparation", "label": prep})
        seen.add("preparation:%s" % prep)
    for candidate in candidates or []:
        node_id = "candidate:%s" % candidate.get("label")
        if node_id not in seen:
            nodes.append({"id": node_id, "type": "mineral_candidate", "label": candidate.get("label")})
            seen.add(node_id)
    edges = []
    for index, rel in enumerate(relations or []):
        edges.append({
            "id": "edge:%d" % index,
            "source": rel.get("source"),
            "target": rel.get("target"),
            "type": rel.get("type"),
            "delta_d": rel.get("delta_d"),
            "intensity_change": rel.get("intensity_change"),
            "rule_id": rel.get("rule_id"),
            "confidence_weight": rel.get("confidence_weight"),
            "explanation": rel.get("explanation"),
        })
    return {"nodes": nodes, "edges": edges}

