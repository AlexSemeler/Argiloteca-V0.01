# =============================================================================
# Projeto...........: Argiloteca – Painel de DRX
# Módulo............: demo_rule_engine.py
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

"""Small demo for the DRX V3 engine.

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

from .diagnostic_decision_tree import interpret_ngc


def demo():
    """
    Executa a etapa `demo` do módulo.

        Returns:
            Resultado documentado pelo contrato do chamador.

        Notes:
            Em fluxos DRX, valores de 2θ, d-spacing, FWHM e intensidade
            relativa devem ser interpretados em conjunto com preparação
            natural, glicolada e calcinada. Nenhum pico isolado deve ser
            tratado como confirmação mineralógica completa.
    """
    return interpret_ngc(
        {"N": [(14.8, 100)], "G": [(17.0, 100)], "C": [(10.0, 90)]},
        {"sample_id": "demo-smectite", "d060": 1.54, "context": ["presalt"], "chemistry": {"Mg": "high"}},
    )


if __name__ == "__main__":
    import json

    print(json.dumps(demo(), indent=2, sort_keys=True))
