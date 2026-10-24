# Original: análise das autoras do artigo do CBSoft'26 “Wireless Connectivity Testing with Mobile Robots: A Bluetooth Low Energy Case Study”.
# Mudanças: arquivos por linha de comando (antes fixos no código) e PNG salvo
# sem abrir janela (--show abre). A lógica de sincronização e os gráficos são
# os mesmos. Linhas em (0,0) do CSV de navegação são descartadas (bug do
# nav_3points.py antes da 1ª pose do AMCL).
#
# Uso: python3 sync_rssi_nav.py NAV.csv "Log nRF.txt" [--out resultados.png] [--show]
# NAV.csv: do nav_3points.py ou do bag_to_nav_csv.py (replay do fleet-ui).
import argparse
import os
import re

import matplotlib
import pandas as pd
import seaborn as sns

def parse_nrf_log(filepath):
    """Lê o log de texto do nRF Connect e extrai o tempo e o RSSI."""
    dados = []
    # Expressão regular para capturar o tempo e o valor de RSSI
    padrao = re.compile(r"(\d{2}:\d{2}:\d{2}\.\d{3})\s+Remote RSSI received:\s+(-?\d+)\s+dBm")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for linha in f:
            match = padrao.search(linha)
            if match:
                tempo_str = match.group(1)
                rssi = int(match.group(2))
                dados.append({'Timestamp_String': tempo_str, 'RSSI': rssi})
                
    df = pd.DataFrame(dados, columns=['Timestamp_String', 'RSSI'])
    # Converte a string de tempo para datetime (assume dia genérico 1900-01-01)
    df['Time'] = pd.to_datetime(df['Timestamp_String'], format='%H:%M:%S.%f')
    return df

def processar_dados(arquivo_nav, arquivo_nrf):
    # 1. Carregar logs
    print("Carregando logs...")
    df_nrf = parse_nrf_log(arquivo_nrf)
    
    df_nav = pd.read_csv(arquivo_nav)
    # Linhas em (0,0): o nav_3points.py gravava antes da 1ª pose do AMCL
    # (aconteceu na corrida real de 2026-05-19 15:57). Não são posições reais.
    df_nav = df_nav[(df_nav['Pos_X'] != 0) | (df_nav['Pos_Y'] != 0)].copy()
    # Converter o tempo do CSV de navegação para datetime
    df_nav['Time'] = pd.to_datetime(df_nav['Timestamp_Legivel'], format='%H:%M:%S.%f')
    
    # 2. Ordenar ambos os DataFrames pelo tempo (obrigatório para merge_asof)
    df_nrf = df_nrf.sort_values('Time').reset_index(drop=True)
    df_nav = df_nav.sort_values('Time').reset_index(drop=True)
    
    # 3. Sincronizar (Merge)
    # Para cada leitura de RSSI, encontra a linha do robô com o tempo MAIS PRÓXIMO
    # tolerance=pd.Timedelta('2s') evita casamentos caso o log de um tenha parado muito antes
    print("Sincronizando odometria com sinal Bluetooth...")
    df_sync = pd.merge_asof(
        df_nrf, 
        df_nav, 
        on='Time', 
        direction='nearest',
        tolerance=pd.Timedelta('2s')
    )
    
    # Remove linhas que não encontraram correspondência (ex: tempos descasados)
    df_sync = df_sync.dropna(subset=['Pos_X', 'Pos_Y'])
    
    return df_sync, df_nav

def gerar_visualizacoes(df_sync, df_nav, nome_imagem='resultados_bt06.png', mostrar=False):
    # Configuração de estilo geral
    sns.set_theme(style="whitegrid")
    
    # Cria uma figura com 3 subplots
    fig = plt.figure(figsize=(16, 10))
    fig.suptitle('Análise de Confiabilidade: Navegação vs. Sinal Bluetooth', fontsize=16, fontweight='bold')

    # --- GRÁFICO 1: Mapa Espacial (Trajetória X,Y com Calor RSSI) ---
    ax1 = plt.subplot(2, 2, (1, 3)) # Ocupa a coluna da esquerda inteira
    
    # ADICIONADO .to_numpy() PARA CORRIGIR O ERRO
    ax1.plot(df_nav['Pos_X'].to_numpy(), df_nav['Pos_Y'].to_numpy(), color='gray', alpha=0.5, label='Trajetória Completa', zorder=1)
    
    # Plota os pontos onde houve leitura de RSSI, coloridos pela força do sinal
    scatter = ax1.scatter(
        df_sync['Pos_X'].to_numpy(), df_sync['Pos_Y'].to_numpy(), 
        c=df_sync['RSSI'].to_numpy(), cmap='RdYlGn', s=100, edgecolor='black', zorder=2
    )
    
    # Adiciona anotações para início e fim do teste (como pegamos apenas um valor com .iloc[0], não dá erro)
    ax1.scatter(df_nav['Pos_X'].iloc[0], df_nav['Pos_Y'].iloc[0], c='blue', s=150, marker='s', label='Partida', zorder=3)
    ax1.scatter(df_nav['Pos_X'].iloc[-1], df_nav['Pos_Y'].iloc[-1], c='red', s=150, marker='X', label='Destino', zorder=3)
    
    cbar = plt.colorbar(scatter, ax=ax1)
    cbar.set_label('RSSI (dBm)', fontsize=12)
    ax1.set_title('Mapa de Trajetória: Posição do Robô vs Força do Sinal', fontsize=14)
    ax1.set_xlabel('Posição X (m)')
    ax1.set_ylabel('Posição Y (m)')
    ax1.legend()
    ax1.axis('equal') # Mantém a proporção do mapa

    # --- GRÁFICO 2: RSSI ao Longo do Tempo ---
    ax2 = plt.subplot(2, 2, 2)
    ax2.plot(df_sync['Time'].to_numpy(), df_sync['RSSI'].to_numpy(), marker='o', linestyle='-', color='#1f77b4')
    ax2.set_title('Decaimento do Sinal no Tempo', fontsize=14)
    ax2.set_ylabel('RSSI (dBm)')
    ax2.set_xlabel('Hora')
    # Formata o eixo X para mostrar apenas HH:MM:SS
    ax2.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter('%H:%M:%S'))

    # --- GRÁFICO 3: RSSI vs Distância Restante ---
    ax3 = plt.subplot(2, 2, 4)
    ax3.scatter(df_sync['Distancia_Restante'].to_numpy(), df_sync['RSSI'].to_numpy(), color='coral', s=50, edgecolor='black')
    sns.regplot(x='Distancia_Restante', y='RSSI', data=df_sync, ax=ax3, scatter=False, color='red', line_kws={"linestyle": "--"})
    
    ax3.set_title('Correlação: Distância para o Alvo vs Sinal Bluetooth', fontsize=14)
    ax3.set_ylabel('RSSI (dBm)')
    ax3.set_xlabel('Distância Restante (m)')

    plt.tight_layout(rect=[0, 0.03, 1, 0.95]) # Ajusta o layout para não cortar o suptitle
    
    # Salva e exibe
    plt.savefig(nome_imagem, dpi=300)
    print(f"✅ Gráficos gerados com sucesso e salvos como '{nome_imagem}'")
    if mostrar:
        plt.show()

plt = None


def main():
    global plt
    ap = argparse.ArgumentParser(description="Sincroniza o log de navegação com o log de RSSI do nRF Connect e gera os gráficos.")
    ap.add_argument("nav", help="CSV de navegação (nav_3points.py ou bag_to_nav_csv.py)")
    ap.add_argument("nrf", help="log de texto exportado do nRF Connect")
    ap.add_argument("--out", default="resultados_bt06.png", help="PNG de saída")
    ap.add_argument("--show", action="store_true", help="abre a janela do gráfico (precisa de tela)")
    args = ap.parse_args()
    if not args.show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as _plt
    plt = _plt

    if not (os.path.exists(args.nav) and os.path.exists(args.nrf)):
        print(f"Arquivos não encontrados: {args.nav} / {args.nrf}")
        return 1
    df_sincronizado, df_completo = processar_dados(args.nav, args.nrf)
    if df_sincronizado.empty:
        print("Erro: Não foi possível sincronizar os dados. Os timestamps coincidem?")
        return 1
    gerar_visualizacoes(df_sincronizado, df_completo, args.out, args.show)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
