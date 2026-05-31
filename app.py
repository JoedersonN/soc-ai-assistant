#!/usr/bin/env python3
"""
SOC AI Assistant
Analisa logs e eventos de segurança em tempo real usando IA local via Ollama.
Autor: Joederson Neves | github.com/JoedersonN
"""

from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import requests
import json
import re
from datetime import datetime
from collections import deque

app = Flask(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2:3b"

# Histórico de eventos em memória (últimos 100)
event_log = deque(maxlen=100)

SYSTEM_PROMPT = """You are an expert SOC (Security Operations Center) analyst specializing in Blue Team operations.
Your role is to analyze security events, logs, and alerts in real time and provide clear, actionable analysis.

When analyzing events, always respond in Brazilian Portuguese and structure your response as:

**SEVERIDADE:** [CRÍTICO / ALTO / MÉDIO / BAIXO / INFO]
**TIPO DE ATAQUE:** [nome técnico do ataque ou evento]
**ANÁLISE:** [explain what is happening in 2-3 sentences]
**IMPACTO POTENCIAL:** [what could happen if not addressed]
**AÇÃO RECOMENDADA:** [specific actionable steps, numbered]
**INDICADORES (IOCs):** [IPs, hashes, domains, or patterns to watch for]

Be concise, technical, and actionable. Think like a Tier 2 SOC analyst."""


def query_ollama(prompt: str, stream: bool = True):
    """Envia prompt ao Ollama e retorna resposta."""
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "system": SYSTEM_PROMPT,
        "stream": stream,
        "options": {
            "temperature": 0.3,
            "top_p": 0.9,
        }
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, stream=stream, timeout=60)
        response.raise_for_status()
        return response
    except requests.exceptions.ConnectionError:
        return None
    except requests.exceptions.Timeout:
        return None


def classify_severity(text: str) -> str:
    """Classifica severidade baseado em palavras-chave no evento."""
    text_lower = text.lower()
    if any(k in text_lower for k in ["root login", "ransomware", "critical", "exploit", "shell", "meterpreter", "privilege escalation"]):
        return "CRÍTICO"
    elif any(k in text_lower for k in ["brute force", "failed password", "syn flood", "malware", "backdoor", "unauthorized"]):
        return "ALTO"
    elif any(k in text_lower for k in ["port scan", "invalid user", "after hours", "suspicious", "anomaly", "dns"]):
        return "MÉDIO"
    elif any(k in text_lower for k in ["login", "access", "connection", "warning"]):
        return "BAIXO"
    return "INFO"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """Analisa um evento de segurança via Ollama com streaming."""
    data = request.get_json()
    event_text = data.get("event", "").strip()

    if not event_text:
        return jsonify({"error": "Nenhum evento fornecido."}), 400

    severity = classify_severity(event_text)
    timestamp = datetime.now().strftime("%H:%M:%S")

    # Salva no log
    event_log.appendleft({
        "timestamp": timestamp,
        "event": event_text[:120],
        "severity": severity,
    })

    prompt = f"""Analise este evento de segurança detectado em {timestamp}:

EVENTO: {event_text}

Forneça análise completa seguindo o formato especificado."""

    def generate():
        response = query_ollama(prompt, stream=True)
        if response is None:
            yield f"data: {json.dumps({'error': 'Ollama não está rodando. Execute: ollama serve'})}\n\n"
            return

        for line in response.iter_lines():
            if line:
                try:
                    chunk = json.loads(line)
                    token = chunk.get("response", "")
                    done = chunk.get("done", False)
                    yield f"data: {json.dumps({'token': token, 'done': done})}\n\n"
                    if done:
                        break
                except json.JSONDecodeError:
                    continue

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@app.route("/api/events", methods=["GET"])
def get_events():
    """Retorna histórico de eventos."""
    return jsonify(list(event_log))


@app.route("/api/status", methods=["GET"])
def status():
    """Verifica se Ollama está rodando."""
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        return jsonify({"online": True, "models": models})
    except Exception:
        return jsonify({"online": False, "models": []})


@app.route("/api/quick", methods=["POST"])
def quick_analyze():
    """Análise rápida de um log bruto (auth.log, etc)."""
    data = request.get_json()
    log_lines = data.get("log", "").strip()

    if not log_lines:
        return jsonify({"error": "Nenhum log fornecido."}), 400

    prompt = f"""Analise estas linhas de log de segurança e identifique os eventos mais críticos:

{log_lines[:2000]}

Forneça um resumo dos principais eventos suspeitos encontrados, ordenados por severidade."""

    def generate():
        response = query_ollama(prompt, stream=True)
        if response is None:
            yield f"data: {json.dumps({'error': 'Ollama não está rodando.'})}\n\n"
            return
        for line in response.iter_lines():
            if line:
                try:
                    chunk = json.loads(line)
                    token = chunk.get("response", "")
                    done = chunk.get("done", False)
                    yield f"data: {json.dumps({'token': token, 'done': done})}\n\n"
                    if done:
                        break
                except json.JSONDecodeError:
                    continue

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


if __name__ == "__main__":
    print("\n╔══════════════════════════════════════╗")
    print("║       SOC AI ASSISTANT — v1.0        ║")
    print("║   github.com/JoedersonN             ║")
    print("╚══════════════════════════════════════╝")
    print(f"\n[*] Modelo: {MODEL}")
    print("[*] Acesse: http://localhost:5000\n")
    app.run(debug=False, host="0.0.0.0", port=5000)
