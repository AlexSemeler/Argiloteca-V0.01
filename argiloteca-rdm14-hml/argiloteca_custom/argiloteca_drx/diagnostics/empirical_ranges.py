# =============================================================================
# Projeto...........: Argiloteca – Painel de DRX
# Módulo............: empirical_ranges.py
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

"""Loader placeholder for locally built empirical ranges.

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

from .diagnostic_behavior_rules import POLICY


EMPIRICAL_RANGES = {
    "policy": POLICY,
    "source": "argiloteca_local_validated_patterns",
    "ranges": {},
}


def load_empirical_ranges():
    """
    Executa a etapa `load_empirical_ranges` do módulo.

        Returns:
            Resultado documentado pelo contrato do chamador.

        Notes:
            Em fluxos DRX, valores de 2θ, d-spacing, FWHM e intensidade
            relativa devem ser interpretados em conjunto com preparação
            natural, glicolada e calcinada. Nenhum pico isolado deve ser
            tratado como confirmação mineralógica completa.
    """
    return EMPIRICAL_RANGES
