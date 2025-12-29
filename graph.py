import re
import os
from datetime import datetime
from typing import Literal
from langgraph.graph import StateGraph, START, END
from google import genai
from google.genai import types

# Importamos nuestros módulos locales
from state import LiaState
import tools
import utils

# Configuración básica
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION = os.getenv("GCP_LOCATION")

# --- NODO 1: ANÁLISIS DE ENTRADA ---
def analizar_input(state: LiaState):
    """
    1. Escucha activa de correos (Regex).
    2. Ejecuta el análisis de IA unificado.
    """
    messages = state["messages"]
    user_message = messages[-1]["parts"][0] if isinstance(messages[-1]["parts"], list) else str(messages[-1]["parts"])
    
    # 1. Regex Email (Global)
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    found_emails = re.findall(email_pattern, user_message)
    nuevo_email_detectado = None
    
    if found_emails:
        email_candidato = found_emails[0].lower().strip()
        if email_candidato != state.get("email_usuario"):
            nuevo_email_detectado = email_candidato
            print(f"📧 [Graph] Nuevo email detectado por regex: {nuevo_email_detectado}")

    # 2. Preparar historial
    hist_txt = "\n".join([f"{m['role']}: {m['parts'][0]}" for m in state["messages"][-6:]])

    analisis = utils.analizar_contexto_unificado(
        user_message=user_message,
        history_text=hist_txt,
        fecha_contexto=state.get("fecha_cita_potencial"),
        email_actual=state.get("email_usuario"),
        esperando_email=state.get("esperando_confirmacion_email"),
        project_id=PROJECT_ID,
        location=LOCATION
    )

    updates = {
        "email_usuario": nuevo_email_detectado if nuevo_email_detectado else state.get("email_usuario"),
    }
    
    if nuevo_email_detectado:
        info = state["info_cliente"].copy()
        info["email"] = nuevo_email_detectado
        updates["info_cliente"] = info

    return {"analisis_temp": analisis, **updates}

# --- NODO 2: LÓGICA DE NEGOCIO (CORREGIDO) ---
def gestionar_logica(state: LiaState):
    analisis = state.get("analisis_temp", {}) 
    if not analisis: 
        return {"system_context_instruction": "Error en análisis."}

    user_message = state["messages"][-1]["parts"][0] if isinstance(state["messages"][-1]["parts"], list) else str(state["messages"][-1]["parts"])
    
    # Desempaquetar
    datos_lead = state["datos_lead"].copy()
    fecha_contexto = state.get("fecha_cita_potencial")
    asesor = state.get("asesor_asignado")
    esperando_email = state.get("esperando_confirmacion_email")
    email_usuario = state.get("email_usuario")
    fecha_final_cita = state.get("fecha_cita_final")
    
    contexto_extra = ""
    status = "continue"
    cita_agendada_data = None

    # A. RECHAZO
    if analisis.get("es_rechazo"):
        motivo = analisis.get("motivo_rechazo", "Desinterés")
        tools.guardar_no_interesado_sheet(state["info_cliente"], motivo)
        return {
            "conversation_status": "finished",
            "motivo_rechazo": motivo,
            "system_context_instruction": "El usuario rechazó explícitamente. Despídete amablemente y corta la conversación."
        }

    # B. ACTUALIZAR DATOS LEAD
    datos_recibidos_ahora = False
    datos_lead_extracted = analisis.get("datos_lead", {})
    
    if datos_lead_extracted.get("tiene_inmuebles"):
        datos_lead["inmuebles"] = str(datos_lead_extracted.get("valor_inmuebles"))
        datos_recibidos_ahora = True
    
    if datos_lead_extracted.get("respondio_fondo"):
        datos_lead["fondo_validado"] = True
        datos_recibidos_ahora = True
        val = datos_lead_extracted.get("nivel_fondo", "")
        datos_lead["nivel_fondo"] = "menor" if "menor" in val.lower() else "mayor"

    completos = datos_lead["inmuebles"] and datos_lead["fondo_validado"]
    
    if completos and datos_recibidos_ahora:
        contexto_extra = "\n[SISTEMA: Datos guardados. El cliente CALIFICA. Avanza a FASE 4: Pregunta '¿Para cuándo te gustaría agendar?']"

    # C. FECHAS
    intencion_fecha = analisis.get("intencion_fecha", {})
    nueva_fecha_detectada = False
    
    if completos and intencion_fecha.get("menciona_fecha"):
        fecha_iso = intencion_fecha.get("fecha_iso")
        if fecha_iso:
            fecha_contexto = fecha_iso
            nueva_fecha_detectada = True
            esperando_email = False
            fecha_final_cita = None
            
            if not asesor:
                asesor = tools.seleccionar_mejor_asesor(datos_lead)
            
            msg_cupos, slots = tools.obtener_cupos_por_fecha(fecha_contexto, asesor)
            
            # --- 🛠️ HELPER PARA FECHA LEGIBLE ---
            # Convertimos 2025-12-27 a "Sábado 27" para que la IA no se confunda
            try:
                dt_obj = datetime.strptime(fecha_iso, "%Y-%m-%d")
                dias_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
                nombre_dia = dias_es[dt_obj.weekday()]
                fecha_texto_claro = f"{nombre_dia} {dt_obj.day}"
            except:
                fecha_texto_claro = fecha_iso

            if msg_cupos.startswith("ES FESTIVO"):
                nombre_festivo = msg_cupos.replace("ES FESTIVO: ", "").strip()
                contexto_extra = (
                    f"\n[SISTEMA: La fecha solicitada ({fecha_texto_claro}) es el festivo '{nombre_festivo}'. "
                    f"INSTRUCCIÓN: Dile: 'Esa fecha es festivo ({nombre_festivo}) 🇨🇴 y estamos descansando. ¿Qué tal si miramos un día hábil?' "
                    f"NO uses la palabra 'hoy' a menos que la fecha sea hoy.]"
                )
                fecha_contexto = None
                
            elif msg_cupos.startswith("NO DISPONIBLE"): # Domingo
                contexto_extra = (
                     f"\n[SISTEMA: La fecha ({fecha_texto_claro}) es Domingo. "
                     f"INSTRUCCIÓN: Di: 'Te cuento que los domingos tomamos un respiro 🔋. ¿Te queda bien algún día entre semana?']"
                )
                fecha_contexto = None

            elif msg_cupos == "AGENDA LLENA":
                contexto_extra = f"\n[SISTEMA: Agenda llena para {fecha_texto_claro}. Pide otra fecha.]"
                fecha_contexto = None
                
            elif msg_cupos.startswith("Error"):
                contexto_extra = "\n[SISTEMA: Error técnico verificando agenda. Pide disculpas.]"
                fecha_contexto = None
                
            else:
                # --- 🎯 CORRECCIÓN CLAVE AQUÍ ---
                contexto_extra = (
                    f"\n[SISTEMA: Cupos disponibles para la fecha REAL: {fecha_texto_claro} (ISO: {fecha_iso})].\n"
                    f"{msg_cupos}\n"
                    f"INSTRUCCIÓN: Ofrécelos diciendo explícitamente 'Para este {fecha_texto_claro} tengo...'. "
                    f"⚠️ IMPORTANTE: IGNORA cualquier otro número de día (como 28 o 29) que el usuario haya mencionado antes. "
                    f"La única fecha válida es {fecha_texto_claro}."
                )

    # D. CONFIRMACIÓN EMAIL Y CIERRE
    info_email = analisis.get("confirmacion_email", {})
    
    if esperando_email and not nueva_fecha_detectada:
        confirmado = False
        nuevo_mail_confirmacion = info_email.get("nuevo_email")
        
        if nuevo_mail_confirmacion:
            email_usuario = nuevo_mail_confirmacion
            confirmado = True
        elif info_email.get("es_confirmacion"):
            confirmado = True
            
        if confirmado:
            evt = tools.crear_evento_calendar(asesor, email_usuario, state["info_cliente"]["nombre"], fecha_final_cita)
            if evt:
                info_final = state["info_cliente"].copy()
                info_final["email"] = email_usuario
                tools.guardar_lead_sheet(datos_lead, info_final, asesor, fecha_final_cita)
                
                cita_agendada_data = evt
                # Formatear la fecha final para el mensaje de despedida también
                try:
                    dt_final = datetime.fromisoformat(fecha_final_cita)
                    hora_fmt = dt_final.strftime("%I:%M %p").lower()
                    fecha_fmt = f"{dt_final.day}/{dt_final.month}"
                except:
                    hora_fmt = ""
                    fecha_fmt = ""

                contexto_extra = (
                    f"\n[SISTEMA: Cita creada EXITOSAMENTE. ID: {evt['id']}. Link: {evt['meet_link']}]. "
                    f"INSTRUCCIÓN: Despídete confirmando: 'Quedó agendado para el {fecha_fmt} a las {hora_fmt}'. "
                    f"Confirma que enviaste la invitación a {email_usuario}."
                )
                status = "finished"
                esperando_email = False
                fecha_contexto = None
            else:
                contexto_extra = "\n[SISTEMA: Error creando la cita en Calendar. Pide intentar de nuevo.]"
        else:
             contexto_extra = f"\n[SISTEMA: Falta confirmar. Pregunta: '¿Confirmo la cita con {email_usuario} o uso otro?']"

    # E. SELECCIÓN DE HORA
    intencion_hora = analisis.get("intencion_hora", {})
    if completos and fecha_contexto and not nueva_fecha_detectada and not esperando_email:
        if intencion_hora.get("menciona_hora"):
            hora_simple = intencion_hora.get("hora_simple") 
            msg_cupos, slots_reales = tools.obtener_cupos_por_fecha(fecha_contexto, asesor)
            
            hora_valida = None
            posibles_formatos = []
            try:
                base_dt = datetime.strptime(fecha_contexto, "%Y-%m-%d")
                hora_dt = datetime.strptime(hora_simple, "%H:%M")
                
                fecha_completa_dt = base_dt.replace(hour=hora_dt.hour, minute=hora_dt.minute)
                slot_usuario = fecha_completa_dt.strftime('%I:%M %p').lower()
                
                posibles_formatos.append(slot_usuario)
                if "am" in slot_usuario: posibles_formatos.append(slot_usuario.replace("am", "pm"))
                else: posibles_formatos.append(slot_usuario.replace("pm", "am"))
            except Exception as e:
                print(f"⚠️ Error parseando hora usuario: {e}")

            for slot_candidato in posibles_formatos:
                if slot_candidato in slots_reales:
                    hora_valida = slot_candidato
                    
                    is_pm = "pm" in hora_valida
                    parts = hora_valida.replace("am","").replace("pm","").strip().split(":")
                    h = int(parts[0])
                    m = int(parts[1])
                    if is_pm and h != 12: h += 12
                    if not is_pm and h == 12: h = 0
                    
                    dt_final = datetime.strptime(fecha_contexto, "%Y-%m-%d").replace(hour=h, minute=m)
                    fecha_final_cita = dt_final.isoformat()
                    break
            
            if hora_valida:
                esperando_email = True
                contexto_extra = (
                    f"\n[SISTEMA: La hora {hora_valida} es válida. RECUERDA: Aún NO has agendado, falta confirmar el email.]\n"
                    f"INSTRUCCIÓN: Dile que esa hora está perfecta. PREGUNTA OBLIGATORIA: '¿Confirmo la cita con tu correo {email_usuario} o prefieres otro?'"
                )
            else:
                contexto_extra = (
                    f"\n[SISTEMA: El usuario pidió {hora_simple} pero NO está disponible.]\n"
                    f"Cupos reales: {slots_reales}\n"
                    f"INSTRUCCIÓN: Di 'Uy, ese espacio ya se ocupó 😅'. Ofrece los cupos disponibles de la lista."
                )

    if (not completos) and ("agendar" in user_message.lower()):
        contexto_extra += "\n[SISTEMA] ALERTA: Faltan datos (inmuebles/fondo). NO AGENDES AÚN. Pídelos."

    return {
        "datos_lead": datos_lead,
        "fecha_cita_potencial": fecha_contexto,
        "asesor_asignado": asesor,
        "email_usuario": email_usuario,
        "esperando_confirmacion_email": esperando_email,
        "fecha_cita_final": fecha_final_cita,
        "conversation_status": status,
        "cita_agendada": cita_agendada_data, 
        "system_context_instruction": contexto_extra
    }

# --- NODO 3: GENERACIÓN DE RESPUESTA ---
def generar_respuesta(state: LiaState):
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    
    system_instr = utils.generar_system_instruction(state["info_cliente"].get("nombre", "Usuario"))
    contexto_sistema = state.get("system_context_instruction", "")
    
    gemini_msgs = []
    for m in state["messages"]:
        gemini_msgs.append(types.Content(role=m["role"], parts=[types.Part.from_text(text=str(m["parts"][0]))]))
    
    last_msg_text = gemini_msgs[-1].parts[0].text
    if contexto_sistema:
        gemini_msgs[-1].parts[0].text = last_msg_text + f"\n{contexto_sistema}"

    config = types.GenerateContentConfig(
        temperature=0.3, 
        max_output_tokens=1024, 
        system_instruction=system_instr
    )

    try:
        resp = client.models.generate_content(
            model="gemini-2.0-flash-lite-001", 
            contents=gemini_msgs, 
            config=config
        )
        text_resp = resp.text
    except Exception:
        text_resp = "Lo siento, tuve un error de conexión. ¿Me repites?"

    text_resp = text_resp.replace("```", "").strip()
    
    return {
        "messages": [{"role": "model", "parts": [text_resp]}],
        "system_context_instruction": "" 
    }

# --- DEFINICIÓN DEL GRAFO (AJUSTE 2) ---
workflow = StateGraph(LiaState)

workflow.add_node("analizar", analizar_input)
workflow.add_node("logica", gestionar_logica)
workflow.add_node("generar", generar_respuesta)

# FLUJO LINEAL: analizar -> logica -> generar -> END
# Eliminamos la condicional intermedia para asegurar que SIEMPRE genere respuesta
workflow.add_edge(START, "analizar")
workflow.add_edge("analizar", "logica")
workflow.add_edge("logica", "generar")
workflow.add_edge("generar", END)

app_graph = workflow.compile()