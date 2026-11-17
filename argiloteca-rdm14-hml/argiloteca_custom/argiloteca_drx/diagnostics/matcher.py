# =============================================================================
# Projeto...........: Argiloteca – Painel de DRX
# Módulo............: matcher.py
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

"""Public peak matcher API.

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

from .evidences import normalize_peaks
from .range_comparator import compare_ranges


def match_peak(peak, source="all", literature=None, empirical=None, presalt=None):
    """
    Executa a etapa `match_peak` do módulo.

        Args:
            peak:
                Parâmetro utilizado pela etapa `match_peak`.
            source:
                Parâmetro utilizado pela etapa `match_peak`.
            literature:
                Parâmetro utilizado pela etapa `match_peak`.
            empirical:
                Parâmetro utilizado pela etapa `match_peak`.
            presalt:
                Parâmetro utilizado pela etapa `match_peak`.
        Returns:
            Resultado documentado pelo contrato do chamador.

        Notes:
            Em fluxos DRX, valores de 2θ, d-spacing, FWHM e intensidade
            relativa devem ser interpretados em conjunto com preparação
            natural, glicolada e calcinada. Nenhum pico isolado deve ser
            tratado como confirmação mineralógica completa.
    """
    peaks = {"N": [peak] if isinstance(peak, dict) else [{"d": peak, "intensity": 1.0}]}
    normalized = normalize_peaks(peaks)
    result = compare_ranges(normalized, literature=literature, empirical=empirical, presalt=presalt)
    if source == "literature":
        result["empirical_matches"] = []
        result["presalt_matches"] = []
    elif source == "empirical":
        result["literature_matches"] = []
        result["presalt_matches"] = []
    elif source == "presalt":
        result["literature_matches"] = []
        result["empirical_matches"] = []
    elif source == "both":
        result["presalt_matches"] = []
    result["combined_candidates"] = sorted({row["mineral"] for key in ("literature_matches", "empirical_matches", "presalt_matches") for row in result[key]})
    return result

