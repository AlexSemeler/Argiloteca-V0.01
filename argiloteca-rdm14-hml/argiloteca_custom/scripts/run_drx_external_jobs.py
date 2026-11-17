#!/usr/bin/env python3
# =============================================================================
# Projeto...........: Argiloteca – Painel de DRX
# Módulo............: run_drx_external_jobs.py
#
# Descrição.........:
# Executa tarefas operacionais de processamento, indexação, validação ou organização de dados DRX.
#
# Autor.............:
# Alexandre Ribas Semeler
# alexandre.semeler@ufrgs.br
#
# Última atualização:
# 2026-06-25
#
# =============================================================================

"""
Projeto: Painel DRX Argiloteca

Descrição:
Offline worker for filesystem-backed DRX external jobs. GSAS-II/DARA are never executed inside the Flask request path. This worker claims queued jobs and runs an external command only when the corresponding adapter environment variable is configured.

Autores:
- Alexandre Ribas Semeler
  E-mail: alexandre.semeler@ufrgs.br



Projeto:
Argiloteca / CPAA

Licença:
Preservar licença existente no repositório.

Última revisão:
2026-06-21

Observação:
Este arquivo integra o sistema de análise, comparação e interpretação de difratogramas de raios X para argilominerais.


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

import argparse
import sys
from pathlib import Path


CUSTOM_DIR = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parents[2]
for path in (APP_DIR, CUSTOM_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from argiloteca.services.drx_external_jobs import claim_next_external_job, run_external_job_adapter


def main():
    """
    Executa uma etapa coesa do fluxo do módulo, mantendo contratos de entrada e saída usados pelo painel Argiloteca.
    
    Args:
        Nenhum argumento explícito.
    Returns:
        Resultado produzido pela etapa, quando aplicável ao contrato do chamador.
    Raises:
        Exception: Propaga erros das dependências quando a validação ou o processamento falha.
    """
    parser = argparse.ArgumentParser(description="Run queued DRX external jobs.")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of queued jobs to process. 0 means no fixed limit.")
    args = parser.parse_args()
    processed = 0
    while True:
        if args.limit and processed >= args.limit:
            break
        job = claim_next_external_job()
        if not job:
            break
        run_external_job_adapter(job)
        processed += 1
        if args.once:
            break
    print(f"processed={processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
