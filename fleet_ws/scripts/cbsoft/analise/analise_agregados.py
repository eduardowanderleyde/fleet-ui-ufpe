# Original: análise agregada das autoras do artigo do CBSoft'26 “Wireless Connectivity Testing with Mobile Robots: A Bluetooth Low Energy Case Study”.
# Mudanças:
# - arquivos por linha de comando (antes a lista ENSAIOS era fixa no código);
# - PNG salvo sem abrir janela (--show abre);
# - ponto zero ("Base (Celular)"): antes era a 1ª linha já SINCRONIZADA da
#   bateria 1, que pode cair segundos depois da partida (e, se essa linha
#   estivesse em (0,0) por causa do bug do nav_3points.py, a distância saía
#   ~17 m errada). Agora é a 1ª pose válida do CSV de navegação da 1ª bateria,
#   ou --base x,y.
#
# Uso: python3 analise_agregados.py --ensaio NAV1.csv "Log1.txt" --ensaio NAV2.csv "Log2.txt" ...
#      [--base x,y] [--out resultado.png] [--show]
import argparse
import os
import re

import matplotlib
import numpy as np
import pandas as pd
import seaborn as sns

plt = None


def parse_nrf_log(filepath):
    """Lê o log de texto do nRF Connect e extrai o tempo e o RSSI."""
    dados = []
    padrao = re.compile(r"(\d{2}:\d{2}:\d{2}\.\d{3})\s+Remote RSSI received:\s+(-?\d+)\s+dBm")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for linha in f:
            match = padrao.search(linha)
            if match:
                tempo_str = match.group(1)
                rssi = int(match.group(2))
                dados.append({'Timestamp_String': tempo_str, 'RSSI': rssi})
                
    df = pd.DataFrame(dados, columns=['Timestamp_String', 'RSSI'])
    df['Time'] = pd.to_datetime(df['Timestamp_String'], format='%H:%M:%S.%f')
    return df

def processar_ensaio(arquivo_nav, arquivo_nrf, num_bateria):
    """Sincroniza um único par de arquivos."""
    if not os.path.exists(arquivo_nav) or not os.path.exists(arquivo_nrf):
        print(f"⚠️  Aviso: Arquivos da Bateria {num_bateria} não encontrados. Ignorando.")
        return None

    df_nrf = parse_nrf_log(arquivo_nrf)
    df_nav = pd.read_csv(arquivo_nav)
    # Linhas em (0,0): o nav_3points.py gravava antes da 1ª pose do AMCL
    # (aconteceu na corrida real de 2026-05-19 15:57). Não são posições reais.
    df_nav = df_nav[(df_nav['Pos_X'] != 0) | (df_nav['Pos_Y'] != 0)].copy()
    
    df_nav['Time'] = pd.to_datetime(df_nav['Timestamp_Legivel'], format='%H:%M:%S.%f')
    
    df_nrf = df_nrf.sort_values('Time').reset_index(drop=True)
    df_nav = df_nav.sort_values('Time').reset_index(drop=True)
    
    # Sincronização
    df_sync = pd.merge_asof(
        df_nrf, df_nav, on='Time', direction='nearest', tolerance=pd.Timedelta('2s')
    )
    df_sync = df_sync.dropna(subset=['Pos_X', 'Pos_Y']).copy()
    
    # Adiciona a identificação da bateria
    df_sync['Bateria'] = f'Bateria {num_bateria}'
    return df_sync

def gerar_visualizacoes_agregadas(df_master, base, nome_imagem='resultado_agregado_v2_corrigido.png', mostrar=False):
    # 1. Calcular Distância a partir da Base (Zero)
    # Pegamos a coordenada inicial da Bateria 1 para ser o "Ponto Zero" (celular estático)
    x0, y0 = base
    
    # Teorema de Pitágoras para saber a distância real do robô até a base em todos os pontos
    df_master['Distancia_Base'] = np.sqrt((df_master['Pos_X'] - x0)**2 + (df_master['Pos_Y'] - y0)**2)

    # 2. Configurações Globais
    sns.set_theme(style="whitegrid")
    fig = plt.figure(figsize=(18, 12))
    fig.suptitle('Análise de Confiabilidade Consolidada (6 Ensaios)', fontsize=18, fontweight='bold')

    # --- GRÁFICO 1: Mapa Espacial Claro (Dispersão Simples) ---
    ax1 = plt.subplot(2, 2, (1, 3))
    
    # Linha de fundo cinza mostrando o caminho
    ax1.plot(df_master['Pos_X'].to_numpy(), df_master['Pos_Y'].to_numpy(), color='lightgray', linewidth=3, zorder=1)
    
    # Plotamos os pontos normais com uma leve transparência para ver onde eles se sobrepõem
    scatter = ax1.scatter(
        df_master['Pos_X'].to_numpy(), 
        df_master['Pos_Y'].to_numpy(), 
        c=df_master['RSSI'].to_numpy(), 
        cmap='RdYlGn', 
        s=80, alpha=0.7, edgecolor='black', linewidth=0.5, zorder=2
    )
    cbar = plt.colorbar(scatter, ax=ax1)
    cbar.set_label('RSSI (dBm)', fontsize=12)
    
    # Marca a base
    ax1.scatter(x0, y0, c='blue', s=200, marker='s', label='Base (Celular)', zorder=3)
    
    ax1.set_title('Mapeamento Espacial: Trajetória Real e Força do Sinal', fontsize=14)
    ax1.set_xlabel('Posição X (m)')
    ax1.set_ylabel('Posição Y (m)')
    ax1.legend()
    ax1.axis('equal') # Super importante: mantém X e Y na mesma proporção física
    ax1.grid(True, linestyle='--', alpha=0.6)

    # --- GRÁFICO 2: Boxplot por Faixa de Distância (0m em diante) ---
    ax2 = plt.subplot(2, 2, 2)
    
    # Criar blocos (bins) de 3 em 3 metros a partir da base
    max_dist = int(np.ceil(df_master['Distancia_Base'].max()))
    bins = np.arange(0, max_dist + 3, 3)
    labels = [f"{i} a {i+3}m" for i in bins[:-1]]
    df_master['Faixa_Dist_Base'] = pd.cut(df_master['Distancia_Base'], bins=bins, labels=labels, right=False)

    sns.boxplot(
        data=df_master,
        x='Faixa_Dist_Base', 
        y='RSSI', 
        ax=ax2,
        palette='viridis',
        hue='Faixa_Dist_Base', 
        legend=False
    )
    ax2.set_title('Variância do Sinal conforme Afastamento', fontsize=14)
    ax2.set_ylabel('RSSI (dBm)')
    ax2.set_xlabel('Distância Percorrida a partir da Base (m)')
    ax2.tick_params(axis='x', rotation=30)

    # --- GRÁFICO 3: Curva de Decaimento Suavizada (Inteiros) ---
    ax3 = plt.subplot(2, 2, 4)
    
    # Agrupamos por metro inteiro (1m, 2m, 3m) para ter uma curva suave!
    df_master['Dist_Inteira'] = df_master['Distancia_Base'].round(0)
    estatisticas = df_master.groupby('Dist_Inteira')['RSSI'].agg(['mean', 'std']).reset_index()
    estatisticas['std'] = estatisticas['std'].fillna(0)

    # Sombra da variação
    ax3.fill_between(
        estatisticas['Dist_Inteira'].to_numpy(),
        (estatisticas['mean'] - estatisticas['std']).to_numpy(),
        (estatisticas['mean'] + estatisticas['std']).to_numpy(),
        color='#1f77b4', alpha=0.2, label='Variação (Desvio Padrão)'
    )
    
    # Linha da média agrupada
    ax3.plot(
        estatisticas['Dist_Inteira'].to_numpy(),
        estatisticas['mean'].to_numpy(),
        color='#1f77b4', linewidth=2.5, marker='o', label='Média por Metro'
    )

    # Pontinhos reais meio transparentes no fundo
    ax3.scatter(
        df_master['Distancia_Base'].to_numpy(), 
        df_master['RSSI'].to_numpy(), 
        c='gray', alpha=0.3, s=15, label='Leituras Individuais'
    )

    # Adiciona uma linha de Tendência Matemática (Regressão de Ordem 2)
    sns.regplot(
        data=df_master,
        x='Distancia_Base',
        y='RSSI',
        scatter=False,
        order=2, # Capta a curva logarítmica de perda de sinal
        ax=ax3,
        color='red',
        line_kws={'linestyle': '--', 'linewidth': 2},
        label='Tendência (Regressão)'
    )
    
    ax3.set_title('Perfil de Decaimento do Sinal', fontsize=14)
    ax3.set_ylabel('RSSI (dBm)')
    ax3.set_xlabel('Distância da Base (m)')
    ax3.legend(loc='lower left', fontsize=10)

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    
    plt.savefig(nome_imagem, dpi=300)
    print(f"\n✅ Nova análise gerada! Imagem salva como '{nome_imagem}'")
    if mostrar:
        plt.show()

def base_da_primeira_bateria(arquivo_nav):
    """1ª pose válida do log de navegação (ignora linhas em (0,0))."""
    df = pd.read_csv(arquivo_nav)
    validas = df[(df['Pos_X'] != 0) | (df['Pos_Y'] != 0)]
    linha = validas.iloc[0] if not validas.empty else df.iloc[0]
    return float(linha['Pos_X']), float(linha['Pos_Y'])


def main():
    global plt
    ap = argparse.ArgumentParser(description="Análise agregada de várias baterias (navegação + RSSI do nRF Connect).")
    ap.add_argument("--ensaio", nargs=2, action="append", metavar=("NAV_CSV", "NRF_LOG"), required=True,
                    help="um par por bateria, na ordem")
    ap.add_argument("--base", help="posição do celular fixo, 'x,y' (padrão: partida da 1ª bateria)")
    ap.add_argument("--out", default="resultado_agregado_v2_corrigido.png", help="PNG de saída")
    ap.add_argument("--show", action="store_true", help="abre a janela do gráfico (precisa de tela)")
    args = ap.parse_args()
    if not args.show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as _plt
    plt = _plt

    dfs_sincronizados = []
    print("Iniciando o processamento em lote dos ensaios...")
    for bateria, (nav, nrf) in enumerate(args.ensaio, start=1):
        print(f"Processando Bateria {bateria}...")
        df_sync = processar_ensaio(nav, nrf, bateria)
        if df_sync is not None and not df_sync.empty:
            dfs_sincronizados.append(df_sync)

    if not dfs_sincronizados:
        print("❌ Nenhum dado pôde ser processado. Verifique os nomes dos arquivos.")
        return 1

    df_master = pd.concat(dfs_sincronizados, ignore_index=True)
    print(f"\nDados consolidados: {len(df_master)} pontos de medição agregados.")
    if args.base:
        base = tuple(float(v) for v in args.base.split(","))
    else:
        base = base_da_primeira_bateria(args.ensaio[0][0])
    print(f"Base (celular fixo): x={base[0]:.3f} y={base[1]:.3f}")
    gerar_visualizacoes_agregadas(df_master, base, args.out, args.show)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
