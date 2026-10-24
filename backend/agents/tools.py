"""
Especificação das ferramentas expostas ao Planner (formato de tool use da
Claude API). Cada entrada aponta para um método de Executor ou Analyst — o
Planner nunca chama outra coisa além disso.
"""
from __future__ import annotations

TOOL_SPECS: list[dict] = [
    {
        "name": "list_robots",
        "description": "Lista os IDs dos robôs conhecidos pela frota.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_routes",
        "description": "Lista as rotas salvas, opcionalmente filtradas por robô.",
        "input_schema": {
            "type": "object",
            "properties": {"robot_id": {"type": "string", "description": "ID do robô, ou vazio para rotas globais."}},
        },
    },
    {
        "name": "get_robot_status",
        "description": "Estado atual de um robô: papel, nav_state, rota, coleta ligada, pose.",
        "input_schema": {
            "type": "object",
            "properties": {"robot_id": {"type": "string"}},
            "required": ["robot_id"],
        },
    },
    {
        "name": "move_robot",
        "description": "Envia o robô para um waypoint (x, y, yaw) via Nav2.",
        "input_schema": {
            "type": "object",
            "properties": {
                "robot_id": {"type": "string"},
                "x": {"type": "number"},
                "y": {"type": "number"},
                "yaw": {"type": "number", "default": 0.0},
            },
            "required": ["robot_id", "x", "y"],
        },
    },
    {
        "name": "start_recording",
        "description": "Começa a gravar uma rota nomeada a partir da pose atual do robô.",
        "input_schema": {
            "type": "object",
            "properties": {"robot_id": {"type": "string"}, "route_name": {"type": "string"}},
            "required": ["robot_id", "route_name"],
        },
    },
    {
        "name": "stop_recording",
        "description": "Para a gravação de rota em andamento.",
        "input_schema": {"type": "object", "properties": {"robot_id": {"type": "string"}}, "required": ["robot_id"]},
    },
    {
        "name": "replay_route",
        "description": "Reproduz uma rota previamente gravada.",
        "input_schema": {
            "type": "object",
            "properties": {"robot_id": {"type": "string"}, "route_name": {"type": "string"}},
            "required": ["robot_id", "route_name"],
        },
    },
    {
        "name": "start_collection",
        "description": "Liga a coleta de sensores (rosbag2) nos tópicos indicados.",
        "input_schema": {
            "type": "object",
            "properties": {
                "robot_id": {"type": "string"},
                "topics": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["robot_id"],
        },
    },
    {
        "name": "stop_collection",
        "description": "Desliga a coleta de sensores.",
        "input_schema": {"type": "object", "properties": {"robot_id": {"type": "string"}}, "required": ["robot_id"]},
    },
    {
        "name": "run_experiment",
        "description": (
            "Dispara UM record ou UM replay (não uma campanha com repetições — para isso "
            "use run_campaign) e aguarda o resultado. config segue o schema de "
            "RunConfigRequest do backend (command: 'record'|'replay', robot, route, collect, "
            "topics, points, ...)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"config": {"type": "object"}},
            "required": ["config"],
        },
    },
    {
        "name": "run_campaign",
        "description": (
            "Roda uma campanha completa: grava 1 execução baseline (usando `points` como "
            "waypoints) e reproduz a mesma rota `repetitions` vezes, depois roda a análise "
            "automaticamente (RMSE, duração, etc). Ao final, use analyze_experiment ou "
            "compare_runs com o run_id devolvido para interpretar os resultados. Pode levar "
            "vários minutos — é a ferramenta certa para 'rode N repetições e me diga se "
            "alguma ficou fora do esperado'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "robot": {"type": "string", "default": "default"},
                "route": {"type": "string"},
                "points": {
                    "type": "array",
                    "description": "Waypoints [x, y, yaw] da gravação baseline.",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "repetitions": {"type": "integer", "default": 3, "minimum": 1},
                "collect": {"type": "boolean", "default": True},
                "topics": {"type": "array", "items": {"type": "string"}},
                "run_id": {"type": "string", "description": "Opcional — gerado automaticamente se omitido."},
            },
            "required": ["route", "points"],
        },
    },
    {
        "name": "analyze_experiment",
        "description": "Resume uma campanha (fleet_ws/runs/<run_id>) e sinaliza execuções com RMSE acima do limiar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "rmse_threshold_m": {"type": "number", "default": 0.05},
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "diagnose_experiment",
        "description": (
            "Como analyze_experiment, mas para cada execução sinalizada (RMSE acima do "
            "limiar) também sugere uma hipótese de causa (trajetória estática, abortou "
            "cedo, não convergiu no destino, etc) cruzando os sinais já calculados em "
            "summary.json. Use depois de analyze_experiment quando o usuário pedir para "
            "investigar/explicar por que uma execução ficou fora do esperado, não só "
            "listar quais ficaram."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "rmse_threshold_m": {"type": "number", "default": 0.05},
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "compare_runs",
        "description": "Compara duas execuções (labels) de uma mesma campanha via RMSE pareado.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "label_a": {"type": "string"},
                "label_b": {"type": "string"},
            },
            "required": ["run_id", "label_a", "label_b"],
        },
    },
]
