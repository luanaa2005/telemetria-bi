#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera um dashboard HTML autocontido a partir do CSV de telemetria.

Reproduz as transformacoes que hoje vivem no Power Query / DAX do projeto
telemetria.pbip, sem depender do Power BI. Nao le nem escreve nada dentro de
telemetria.Report/ ou telemetria.SemanticModel/.

Uso:
    python3 gerar_dashboard.py                      # le a pasta padrao da rede
    python3 gerar_dashboard.py /caminho/da/pasta    # le o CSV mais recente da pasta
    python3 gerar_dashboard.py arquivo.csv          # le um CSV especifico
    python3 gerar_dashboard.py -o saida.html ...

Saida padrao: dashboard.html (ao lado deste script).
Dependencias: nenhuma (so biblioteca padrao do Python 3.8+).
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime

# ---------------------------------------------------------------------------
# Parametros de negocio
# ---------------------------------------------------------------------------

# Mesmo caminho do parametro CaminhoPasta no modelo semantico.
PASTA_PADRAO = r"\\ger-sinet\telemetria"

# Mesmos valores da coluna calculada "Custo anual E5 + Copilot".
CUSTO_ANUAL_E5 = 3120.60
CUSTO_ANUAL_COPILOT = 2590.08

# Faixas da medida "% E5 Terceiros Color".
LIMITE_CRITICO = 0.50
LIMITE_ATENCAO = 0.25

COLUNAS_NUMERICAS = ("Copilot", "M365 E5", "M365 F3", "M365 F5 Security")

# O esquema da coleta mudou com o tempo: CSVs antigos nao tem M365 F5 Security.
# O Power BI nunca viu isso porque le so o arquivo mais novo. Como aqui lemos a
# serie inteira, so e obrigatorio o que nao tem substituto — o resto assume um
# padrao e o relatorio avisa onde faltou.
COLUNAS_ESSENCIAIS = (
    "Unidade",
    "Subunidade",
    "Qualidade",
    "Situacao funcional",
)

# coluna -> valor quando ela nao existe no arquivo
COLUNAS_OPCIONAIS = {
    "Data da coleta": "",     # cai para a data de modificacao do arquivo
    "Conta": "",
    "Empresa": "",
    "Copilot": "0",
    "M365 E5": "0",
    "M365 F3": "0",
    "M365 F5 Security": "0",
}


# ---------------------------------------------------------------------------
# Leitura do CSV
# ---------------------------------------------------------------------------

def listar_csvs(caminho):
    """Lista os CSVs da entrada, do mais antigo para o mais recente.

    O Power Query usa so o arquivo mais novo (Sorted{0}[Content]) e descarta o
    resto. Aqui a pasta inteira e lida: o ultimo arquivo alimenta as paginas de
    detalhe e todos juntos formam a serie historica.
    """
    if os.path.isfile(caminho):
        return [caminho]

    if not os.path.isdir(caminho):
        raise SystemExit(
            "Nao encontrei '%s'.\n"
            "Passe o caminho de uma pasta com os CSVs ou de um arquivo .csv." % caminho
        )

    # Recursivo de proposito: o Folder.Files() do Power Query varre a pasta e
    # todas as subpastas, entao olhar so a raiz acharia menos arquivos que o
    # Power BI e o historico viria furado.
    candidatos = []
    for raiz, _, arquivos in os.walk(caminho):
        for nome in arquivos:
            if nome.lower().endswith(".csv"):
                candidatos.append(os.path.join(raiz, nome))

    if not candidatos:
        raise SystemExit(
            "Nao achei nenhum .csv em '%s' (nem nas subpastas).\n"
            "Confira o caminho, ou passe a pasta certa como argumento." % caminho
        )

    candidatos.sort(key=os.path.getmtime)
    return candidatos


# A coleta nomeia os arquivos como 03-11-2026-inventarioLicOffice365-050039.
_DATA_NO_NOME = re.compile(r"(?<!\d)(\d{2})-(\d{2})-(\d{4})(?!\d)|(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")


def dia_do_arquivo(arquivo):
    """Dia da coleta, pelo nome do arquivo e, se nao der, pela modificacao.

    O nome e mais confiavel que a data de modificacao: copiar a pasta de rede
    reescreve a modificacao de todos os arquivos e colapsaria o historico num
    dia so, mas o nome sobrevive a copia.
    """
    achado = _DATA_NO_NOME.search(os.path.basename(arquivo))
    if achado:
        d, m, a, a2, m2, d2 = achado.groups()
        try:
            if a:
                return datetime(int(a), int(m), int(d)).strftime("%Y-%m-%d")
            return datetime(int(a2), int(m2), int(d2)).strftime("%Y-%m-%d")
        except ValueError:
            pass    # 31-02-2026 e coisas assim: cai para a modificacao
    return datetime.fromtimestamp(os.path.getmtime(arquivo)).strftime("%Y-%m-%d")


def selecionar(candidatos, limite):
    """Reduz a lista de CSVs ao que de fato vira ponto no historico.

    A coleta roda varias vezes no mesmo dia, e cada arquivo custa alguns MB
    pela rede. Duas reducoes antes de abrir qualquer um:

    1. Um por dia. Execucoes extras do mesmo dia seriam descartadas depois na
       deduplicacao por Data da coleta — ler as tres para jogar duas fora e
       desperdicio de rede. O dia sai do nome do arquivo; a deduplicacao de
       verdade continua acontecendo com a data de dentro do CSV.
    2. So as `limite` coletas mais recentes (0 = todas).

    Devolve (escolhidos, descartados_no_dia, descartados_pelo_limite).
    """
    por_dia = OrderedDict()
    duplicados = 0
    for arquivo in candidatos:                      # ja vem do mais antigo
        dia = dia_do_arquivo(arquivo)
        if dia in por_dia:
            duplicados += 1
        por_dia[dia] = arquivo                      # fica o ultimo do dia

    escolhidos = list(por_dia.values())
    antigos = 0
    if limite and len(escolhidos) > limite:
        antigos = len(escolhidos) - limite
        escolhidos = escolhidos[-limite:]

    return escolhidos, duplicados, antigos


def normalizar(nome):
    """Remove acentos e espacos extras de um nome de coluna, para comparacao."""
    acentos = {
        "á": "a", "à": "a", "ã": "a", "â": "a", "ä": "a",
        "é": "e", "ê": "e", "è": "e",
        "í": "i", "î": "i",
        "ó": "o", "õ": "o", "ô": "o", "ö": "o",
        "ú": "u", "ü": "u",
        "ç": "c",
    }
    texto = (nome or "").strip().lower()
    return "".join(acentos.get(c, c) for c in texto)


def ler_csv(arquivo):
    """Le o CSV e devolve (linhas, colunas_opcionais_ausentes).

    Os nomes de coluna sao normalizados sem acento para que o script continue
    funcionando se a exportacao trocar "Situacao" por "Situação".
    """
    with open(arquivo, "r", encoding="utf-8-sig", newline="") as fh:
        leitor = csv.reader(fh, delimiter=";", quoting=csv.QUOTE_NONE)
        try:
            cabecalho = next(leitor)
        except StopIteration:
            raise SystemExit("O arquivo '%s' esta vazio." % arquivo)

        indice = {normalizar(nome): pos for pos, nome in enumerate(cabecalho)}

        faltando = [c for c in COLUNAS_ESSENCIAIS if normalizar(c) not in indice]
        if faltando:
            raise SystemExit(
                "O arquivo '%s' nao tem as colunas: %s\nColunas encontradas: %s"
                % (os.path.basename(arquivo), ", ".join(faltando), ", ".join(cabecalho))
            )

        ausentes = [c for c in COLUNAS_OPCIONAIS if normalizar(c) not in indice]

        def pegar(linha, coluna):
            pos = indice.get(normalizar(coluna))
            if pos is None:
                return COLUNAS_OPCIONAIS[coluna]
            return linha[pos].strip() if pos < len(linha) else ""

        linhas = []
        for bruta in leitor:
            if not bruta or all(not c.strip() for c in bruta):
                continue

            linha = {
                "data": pegar(bruta, "Data da coleta"),
                "unidade": pegar(bruta, "Unidade"),
                "subunidade": pegar(bruta, "Subunidade"),
                "qualidade": pegar(bruta, "Qualidade").upper(),
                "situacao": pegar(bruta, "Situacao funcional").upper(),
                "conta": pegar(bruta, "Conta"),
                "empresa": pegar(bruta, "Empresa"),
            }
            for coluna in COLUNAS_NUMERICAS:
                linha[coluna] = inteiro(pegar(bruta, coluna))

            # Mesma regra da coluna "Nível" nas tres consultas do modelo.
            linha["nivel"] = (
                "UNIDADE" if linha["unidade"] == linha["subunidade"] else "SUBUNIDADE"
            )
            linha["licencas"] = sum(linha[c] for c in COLUNAS_NUMERICAS)
            linha["classificacao"] = classificar(linha)
            linhas.append(linha)

    if not linhas:
        raise SystemExit("O arquivo '%s' nao tem nenhuma linha de dados." % arquivo)

    return linhas, ausentes


def inteiro(valor):
    """Converte para int tolerando vazio, decimal e separador brasileiro."""
    texto = (valor or "").strip().replace(" ", "")
    if not texto:
        return 0
    texto = texto.replace(".", "").replace(",", ".") if "," in texto else texto
    try:
        return int(round(float(texto)))
    except ValueError:
        return 0


def classificar(linha):
    """Mesma logica da coluna Classificacao em AlocacaoPessoas."""
    tem_premium = linha["M365 E5"] == 1 or linha["Copilot"] == 1
    if linha["situacao"] in ("INATIVO", "NAO_INFORMADO") and tem_premium:
        return "Ociosa"
    if tem_premium and linha["situacao"] == "ATIVO":
        return "Ativa"
    return "Sem licença"


# Fuso no fim da string: Z, -03:00, -0300. O offset do Brasil e negativo, e a
# data tambem tem hifens — por isso a ancora no fim em vez de um split.
_FUSO = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")

FORMATOS_DATA = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y",
)


def parse_data(bruto):
    """Converte o texto da coluna em datetime, ou None se nao der.

    Aceita ISO 8601 com fuso (o que o DateTimeZone.From do Power Query espera)
    e os formatos brasileiros mais comuns. O fuso e descartado, nao convertido:
    e o que o DateTime.From faz com um DateTimeZone — fica a hora de parede.
    """
    texto = (bruto or "").strip()
    if not texto:
        return None

    try:
        quando = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        return quando.replace(tzinfo=None)
    except ValueError:
        pass

    semfuso = _FUSO.sub("", texto.replace("T", " ")).strip()
    semfracao = semfuso.split(".")[0].strip()
    for formato in FORMATOS_DATA:
        try:
            return datetime.strptime(semfracao, formato)
        except ValueError:
            continue
    return None


def data_coleta(linhas):
    """Equivalente a medida Data Coleta: MAX da data da coleta.

    Devolve (datetime_ou_None, amostra_do_valor_bruto). A amostra existe para
    que a mensagem de aviso mostre o que veio no arquivo, em vez de so dizer
    que falhou.
    """
    melhor = None
    amostra = ""
    for linha in linhas:
        bruto = (linha["data"] or "").strip()
        if not bruto:
            continue
        if not amostra:
            amostra = bruto
        quando = parse_data(bruto)
        if quando is not None and (melhor is None or quando > melhor):
            melhor = quando
    return melhor, amostra


def formatar_data(quando):
    return quando.strftime("%d/%m/%Y") if quando else "nao informada"


# ---------------------------------------------------------------------------
# Agregacoes (equivalentes as consultas do modelo semantico)
# ---------------------------------------------------------------------------

def agrupar(linhas):
    """Agrupa por (Nivel, Unidade, Subunidade), como o Table.Group do modelo."""
    grupos = OrderedDict()
    for linha in linhas:
        chave = (linha["nivel"], linha["unidade"], linha["subunidade"])
        grupos.setdefault(chave, []).append(linha)
    return grupos


def visao_gerencial(grupos):
    """Equivalente a consulta 'Visão Gerencial'."""
    saida = []
    for (nivel, unidade, subunidade), itens in grupos.items():
        def licencas_de(qualidade):
            return sum(i["licencas"] for i in itens if i["qualidade"] == qualidade)

        ociosas = sum(
            1
            for i in itens
            if i["situacao"] in ("INATIVO", "NAO_INFORMADO")
            and (i["M365 E5"] == 1 or i["Copilot"] == 1)
        )
        atencao = any(
            i["situacao"] == "INATIVO" and i["licencas"] > 0 for i in itens
        )

        saida.append({
            "nivel": nivel,
            "unidade": unidade,
            "subunidade": subunidade,
            "u1": licencas_de("AUTORIDADE"),
            "u2": licencas_de("SERVIDOR"),
            "u3": licencas_de("TERCEIRIZADO"),
            "u4": licencas_de("ESTAGIARIO"),
            "total": sum(i["licencas"] for i in itens),
            "ociosas": ociosas,
            "situacao": "Atenção" if atencao else "OK",
        })
    return saida


def alocacao_por_unidade(grupos):
    """Equivalente a consulta 'Alocação por unidade'."""
    saida = []
    for (nivel, unidade, subunidade), itens in grupos.items():
        e5 = sum(i["M365 E5"] for i in itens)
        copilot = sum(i["Copilot"] for i in itens)
        e5_terceiros = sum(
            i["M365 E5"] for i in itens if i["qualidade"] == "TERCEIRIZADO"
        )

        def contar(condicao):
            return sum(1 for i in itens if condicao(i))

        terceiro_e5 = lambda i: i["qualidade"] == "TERCEIRIZADO" and i["M365 E5"] == 1

        saida.append({
            "nivel": nivel,
            "unidade": unidade,
            "subunidade": subunidade,
            "e5": e5,
            "copilot": copilot,
            "e5Terceiros": e5_terceiros,
            "pct": 0.0 if e5 == 0 else e5_terceiros / e5,
            "pessoas": contar(lambda i: i["M365 E5"] == 1 or i["Copilot"] == 1),
            "desabilitada": contar(
                lambda i: terceiro_e5(i) and i["conta"] == "Desabilitada"
            ),
            "inativo": contar(lambda i: terceiro_e5(i) and i["situacao"] == "INATIVO"),
            "outro": contar(
                lambda i: terceiro_e5(i)
                and i["situacao"] not in ("ATIVO", "INATIVO")
            ),
            "custo": e5 * CUSTO_ANUAL_E5 + copilot * CUSTO_ANUAL_COPILOT,
        })
    return saida


def por_nivel(linhas):
    """Totais de licencas por Nivel, para os cards da Visao Gerencial."""
    saida = OrderedDict()
    for nivel in ("UNIDADE", "SUBUNIDADE"):
        saida[nivel] = {"e5": 0, "copilot": 0, "f3": 0, "f5": 0}
    for linha in linhas:
        alvo = saida[linha["nivel"]]
        alvo["e5"] += linha["M365 E5"]
        alvo["copilot"] += linha["Copilot"]
        alvo["f3"] += linha["M365 F3"]
        alvo["f5"] += linha["M365 F5 Security"]
    return [dict(nivel=k, **v) for k, v in saida.items()]


def classificacoes(linhas):
    """Contagem por (Nivel, Classificacao), para a composicao de licencas."""
    contagem = OrderedDict()
    for linha in linhas:
        chave = (linha["nivel"], linha["classificacao"])
        contagem[chave] = contagem.get(chave, 0) + 1
    return [
        {"nivel": n, "classificacao": c, "qtd": q}
        for (n, c), q in contagem.items()
    ]


# --- desperdicio -----------------------------------------------------------

# Ordem de precedencia: uma licenca cai em um balde so, para que o simulador
# possa somar os cenarios sem contar a mesma licenca duas vezes.
MOTIVOS = ("desabilitada", "inativo", "naoInformado")


def motivo_desperdicio(linha):
    """Por que esta licenca premium provavelmente esta sendo desperdicada.

    Mais abrangente que a coluna Ociosas do modelo, que olha so a situacao
    funcional: aqui uma conta desabilitada conta como desperdicio mesmo que a
    situacao funcional ainda diga ATIVO.
    """
    if linha["M365 E5"] != 1 and linha["Copilot"] != 1:
        return None
    if linha["conta"].strip().lower() == "desabilitada":
        return "desabilitada"
    if linha["situacao"] == "INATIVO":
        return "inativo"
    if linha["situacao"] == "NAO_INFORMADO":
        return "naoInformado"
    return None


def economia(grupos):
    """Licencas desperdicadas por grupo, separadas por motivo e por produto."""
    saida = []
    for (nivel, unidade, subunidade), itens in grupos.items():
        registro = {"nivel": nivel, "unidade": unidade, "subunidade": subunidade}
        for motivo in MOTIVOS:
            doMotivo = [i for i in itens if motivo_desperdicio(i) == motivo]
            registro[motivo + "E5"] = sum(i["M365 E5"] for i in doMotivo)
            registro[motivo + "Copilot"] = sum(i["Copilot"] for i in doMotivo)
            registro[motivo + "Pessoas"] = len(doMotivo)
        saida.append(registro)
    return saida


# --- fornecedores ----------------------------------------------------------

def fornecedores(linhas):
    """Licencas de terceirizados agrupadas por empresa contratada."""
    grupos = OrderedDict()
    for linha in linhas:
        if linha["qualidade"] != "TERCEIRIZADO":
            continue
        empresa = linha["empresa"].strip() or "(não informada)"
        chave = (linha["nivel"], empresa)
        alvo = grupos.get(chave)
        if alvo is None:
            alvo = {
                "nivel": linha["nivel"], "empresa": empresa,
                "pessoas": 0, "e5": 0, "copilot": 0, "f3": 0, "f5": 0,
                "desabilitada": 0, "inativo": 0, "ativo": 0, "semSituacao": 0,
                "_unidades": set(),
            }
            grupos[chave] = alvo

        alvo["pessoas"] += 1
        alvo["e5"] += linha["M365 E5"]
        alvo["copilot"] += linha["Copilot"]
        alvo["f3"] += linha["M365 F3"]
        alvo["f5"] += linha["M365 F5 Security"]
        alvo["_unidades"].add(linha["unidade"])

        # Baldes exclusivos e exaustivos: somados, dao o total de pessoas.
        if linha["conta"].strip().lower() == "desabilitada":
            alvo["desabilitada"] += 1
        elif linha["situacao"] == "ATIVO":
            alvo["ativo"] += 1
        elif linha["situacao"] == "INATIVO":
            alvo["inativo"] += 1
        else:
            alvo["semSituacao"] += 1

    saida = []
    for alvo in grupos.values():
        # Lista, nao contagem: uma empresa pode aparecer nos dois niveis e o
        # HTML precisa unir os conjuntos antes de contar.
        alvo["unidades"] = sorted(alvo.pop("_unidades"))
        alvo["custo"] = alvo["e5"] * CUSTO_ANUAL_E5 + alvo["copilot"] * CUSTO_ANUAL_COPILOT
        saida.append(alvo)
    return saida


# --- historico -------------------------------------------------------------

def resumo_coleta(linhas, quando, arquivo, faltando=()):
    """Numeros de uma coleta inteira, quebrados por Nivel.

    E o que alimenta a pagina de evolucao: barato de calcular e pequeno o
    bastante para caber no HTML mesmo com dezenas de coletas.
    """
    porNivel = OrderedDict()
    for nivel in ("UNIDADE", "SUBUNIDADE"):
        porNivel[nivel] = {
            "data": quando.strftime("%Y-%m-%d"),
            "rotulo": formatar_data(quando),
            "arquivo": os.path.basename(arquivo),
            "faltando": list(faltando),
            "nivel": nivel,
            "pessoas": 0, "licencas": 0,
            "e5": 0, "copilot": 0, "f3": 0, "f5": 0,
            "e5Terceiros": 0, "ociosas": 0, "ativas": 0, "desperdicio": 0,
        }

    for linha in linhas:
        alvo = porNivel[linha["nivel"]]
        alvo["pessoas"] += 1
        alvo["licencas"] += linha["licencas"]
        alvo["e5"] += linha["M365 E5"]
        alvo["copilot"] += linha["Copilot"]
        alvo["f3"] += linha["M365 F3"]
        alvo["f5"] += linha["M365 F5 Security"]
        if linha["qualidade"] == "TERCEIRIZADO":
            alvo["e5Terceiros"] += linha["M365 E5"]
        if linha["classificacao"] == "Ociosa":
            alvo["ociosas"] += 1
        elif linha["classificacao"] == "Ativa":
            alvo["ativas"] += 1
        if motivo_desperdicio(linha):
            alvo["desperdicio"] += (
                linha["M365 E5"] * CUSTO_ANUAL_E5
                + linha["Copilot"] * CUSTO_ANUAL_COPILOT
            )

    for alvo in porNivel.values():
        alvo["custo"] = alvo["e5"] * CUSTO_ANUAL_E5 + alvo["copilot"] * CUSTO_ANUAL_COPILOT
        alvo["desperdicio"] = round(alvo["desperdicio"], 2)
    return list(porNivel.values())


# ---------------------------------------------------------------------------
# Montagem do HTML
# ---------------------------------------------------------------------------

def construir(arquivos, saida, template, modo="embutido"):
    """Monta o HTML: detalhe do CSV mais recente + historico de todos eles.

    modo="embutido": um arquivo so, com os dados dentro. Abre do disco, vai por
    e-mail, funciona offline.
    modo="externo": dashboard.html + dados.json ao lado. Para publicar num
    servidor web — basta regerar o JSON para a pagina ficar atual.
    """
    historico = []
    vistas = {}          # data da coleta -> posicao, para nao duplicar coleta
    linhas = None        # linhas do arquivo mais recente

    lacunas = OrderedDict()   # coluna ausente -> datas das coletas afetadas

    for arquivo in arquivos:
        atuais, ausentes = ler_csv(arquivo)
        quando, amostra = data_coleta(atuais)

        if quando is None:
            # O nome da pasta e a data de modificacao carregam a data da
            # coleta, entao uma coluna ausente ou num formato novo nao precisa
            # custar o ponto inteiro no historico.
            quando = datetime.fromtimestamp(os.path.getmtime(arquivo))
            motivo = ("a coluna nao existe" if "Data da coleta" in ausentes
                      else "a coluna veio vazia" if not amostra
                      else "nao reconheci o formato %r" % amostra)
            print("  aviso: %s — %s; usando a data do arquivo (%s)"
                  % (os.path.basename(arquivo), motivo, formatar_data(quando)),
                  file=sys.stderr)

        for coluna in ausentes:
            lacunas.setdefault(coluna, []).append(formatar_data(quando))

        chave = quando.strftime("%Y-%m-%d")
        resumo = resumo_coleta(atuais, quando, arquivo, ausentes)
        if chave in vistas:
            # Duas exportacoes da mesma data: vale a mais recente no disco.
            historico[vistas[chave]:vistas[chave] + len(resumo)] = resumo
        else:
            vistas[chave] = len(historico)
            historico.extend(resumo)

        linhas = atuais
        ausentes_recentes = ausentes

    historico.sort(key=lambda r: (r["data"], r["nivel"]))

    arquivo_csv = arquivos[-1]
    grupos = agrupar(linhas)

    dados = {
        "modo": modo,
        "geradoEm": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "arquivoFonte": os.path.basename(arquivo_csv),
        "dataColeta": formatar_data(data_coleta(linhas)[0]),
        "totalLinhas": len(linhas),
        "totalColetas": len(vistas),
        "custoE5": CUSTO_ANUAL_E5,
        "custoCopilot": CUSTO_ANUAL_COPILOT,
        "limiteCritico": LIMITE_CRITICO,
        "limiteAtencao": LIMITE_ATENCAO,
        "visaoGerencial": visao_gerencial(grupos),
        "alocacao": alocacao_por_unidade(grupos),
        "licencasPorNivel": por_nivel(linhas),
        "classificacoes": classificacoes(linhas),
        "economia": economia(grupos),
        "fornecedores": fornecedores(linhas),
        "historico": historico,
        "lacunas": [
            {"coluna": coluna, "coletas": datas}
            for coluna, datas in lacunas.items()
        ],
        "lacunasAtuais": list(ausentes_recentes),
    }

    with open(template, "r", encoding="utf-8") as fh:
        html = fh.read()

    marcador = "/*{{DADOS}}*/"
    if marcador not in html:
        raise SystemExit("O template '%s' nao tem o marcador %s." % (template, marcador))

    payload = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))

    if modo == "externo":
        dados["arquivoJson"] = os.path.join(os.path.dirname(saida) or ".", "dados.json")
        with open(dados["arquivoJson"], "w", encoding="utf-8") as fh:
            fh.write(payload)
        corpo = "null"
    else:
        # </script> dentro do JSON encerraria o bloco <script> do template.
        corpo = payload.replace("</", "<\\/")

    with open(saida, "w", encoding="utf-8") as fh:
        fh.write(html.replace(marcador, corpo))

    return dados


def main():
    aqui = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(
        description="Gera um dashboard HTML autocontido a partir do CSV de telemetria."
    )
    parser.add_argument(
        "entrada",
        nargs="?",
        default=PASTA_PADRAO,
        help="pasta com os CSVs ou um arquivo .csv (padrao: %s)" % PASTA_PADRAO,
    )
    parser.add_argument(
        "-o", "--saida",
        default=os.path.join(aqui, "dashboard.html"),
        help="arquivo HTML de saida (padrao: dashboard.html ao lado do script)",
    )
    parser.add_argument(
        "--historico",
        type=int,
        default=90,
        metavar="N",
        help="quantas coletas mais recentes entram no historico (padrao: 90, "
             "0 = todas). Cada CSV custa alguns MB pela rede",
    )
    parser.add_argument(
        "-m", "--modo",
        choices=("embutido", "externo"),
        default="embutido",
        help="embutido: um arquivo so (padrao). externo: html + dados.json, "
             "para publicar num servidor web",
    )
    parser.add_argument(
        "-t", "--template",
        default=os.path.join(aqui, "template.html"),
        help="template HTML (padrao: template.html ao lado do script)",
    )
    args = parser.parse_args()

    # Falha cedo: ler a pasta inteira de CSVs para so depois descobrir que o
    # destino nao existe desperdicaria o trabalho todo.
    pasta_saida = os.path.dirname(os.path.abspath(args.saida))
    if not os.path.isdir(pasta_saida):
        raise SystemExit(
            "A pasta de saida nao existe: %s\n"
            "Crie a pasta ou corrija o caminho do -o." % pasta_saida
        )
    if not os.path.isfile(args.template):
        raise SystemExit("Nao encontrei o template: %s" % args.template)

    encontrados = listar_csvs(args.entrada)
    arquivos, duplicados, antigos = selecionar(encontrados, args.historico)

    print("CSVs encontrados .: %d" % len(encontrados))
    if duplicados:
        print("  ignorados ......: %d (outra execucao no mesmo dia)" % duplicados)
    if antigos:
        print("  fora do limite .: %d (use --historico 0 para ler tudo)" % antigos)
    print("CSVs lidos .......: %d" % len(arquivos))
    if len(arquivos) > 5:
        print("  lendo, pode demorar...", flush=True)

    dados = construir(arquivos, args.saida, args.template, args.modo)

    tamanho = os.path.getsize(args.saida) / 1024.0
    print("Coletas distintas : %d" % dados["totalColetas"])
    print("Detalhe vindo de .: %s" % dados["arquivoFonte"])
    print("Linhas ...........: %d" % dados["totalLinhas"])
    print("Data da coleta ...: %s" % dados["dataColeta"])
    print("Unidades/subunid .: %d grupos" % len(dados["visaoGerencial"]))
    print("Fornecedores .....: %d" % len({f["empresa"] for f in dados["fornecedores"]}))
    for lacuna in dados["lacunas"]:
        print("Coluna ausente ...: %s em %d coleta(s), contada como zero"
              % (lacuna["coluna"], len(lacuna["coletas"])))
    print("Dashboard gerado .: %s (%.0f KB)" % (args.saida, tamanho))
    if dados.get("arquivoJson"):
        kb = os.path.getsize(dados["arquivoJson"]) / 1024.0
        print("Dados gerados ....: %s (%.0f KB)" % (dados["arquivoJson"], kb))
        print("                    publique os dois na mesma pasta do servidor")


if __name__ == "__main__":
    sys.exit(main())
