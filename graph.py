import re
import os
from datetime import datetime
from langgraph.graph import StateGraph, START, END
from google import genai
from google.genai import types

from state import LiaState
import tools
import utils

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION = os.getenv("GCP_LOCATION")

# --- NODO 1: ANÁLISIS ---
def analizar_input(state: LiaState):
    messages = state["messages"]
    user_message = messages[-1]["parts"][0] if isinstance(messages[-1]["parts"], list) else str(messages[-1]["parts"])
    
    # 1. Recuperación robusta del email base
    email_actual = state.get("email_usuario")
    if not email_actual:
        email_actual = state["info_cliente"].get("email", "")

    # 2. Detección Regex (Prioridad Máxima)
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    found_emails = re.findall(email_pattern, user_message)
    nuevo_email_detectado = None
    email_regex_match = False 
    
    if found_emails:
        email_candidato = found_emails[0].lower().strip()
        nuevo_email_detectado = email_candidato
        email_regex_match = True

    # 3. Preparar historial
    hist_txt = "\n".join([f"{m['role']}: {m['parts'][0]}" for m in state["messages"][-6:]])

    analisis = utils.analizar_contexto_unificado(
        user_message=user_message,
        history_text=hist_txt,
        fecha_contexto=state.get("fecha_cita_potencial"),
        email_actual=email_actual,
        esperando_email=state.get("esperando_confirmacion_email"),
        project_id=PROJECT_ID,
        location=LOCATION
    )

    updates = {
        "email_usuario": nuevo_email_detectado if nuevo_email_detectado else email_actual,
    }
    
    if nuevo_email_detectado:
        info = state["info_cliente"].copy()
        info["email"] = nuevo_email_detectado
        updates["info_cliente"] = info

    analisis["regex_detected"] = email_regex_match
    
    return {"analisis_temp": analisis, **updates}

# --- NODO 2: LÓGICA DE NEGOCIO ---
def gestionar_logica(state: LiaState):
    analisis = state.get("analisis_temp", {}) 
    if not analisis: return {"system_context_instruction": "Error en análisis."}

    # Desempaquetado
    datos_lead = state["datos_lead"].copy()
    fecha_contexto = state.get("fecha_cita_potencial")
    asesor = state.get("asesor_asignado")
    esperando_email = state.get("esperando_confirmacion_email")
    email_usuario = state.get("email_usuario")
    fecha_final_cita = state.get("fecha_cita_final")
    cita_agendada_prev = state.get("cita_agendada") 
    
    # Persistencia del motivo de rechazo (Para no perderlo si el usuario corta el chat)
    motivo_nuevo = analisis.get("motivo_rechazo")
    motivo_previo = state.get("motivo_rechazo")
    motivo_actualizado = motivo_nuevo if motivo_nuevo else motivo_previo
    
    if not email_usuario:
        email_usuario = state["info_cliente"].get("email", "tu correo")

    contexto_extra = ""
    status = "continue"
    cita_agendada_data = cita_agendada_prev

    # -----------------------------------------------------------------
    # CASO ESPECIAL: Cita ya agendada -> CIERRE Y GUARDADO FINAL
    # -----------------------------------------------------------------
    if cita_agendada_prev:
        # Intentamos extraer datos si el usuario los dio ahora
        datos_lead_extracted = analisis.get("datos_lead", {})
        hubo_actualizacion = False
        
        if datos_lead_extracted.get("tiene_inmuebles"):
            datos_lead["inmuebles"] = str(datos_lead_extracted.get("valor_inmuebles"))
            hubo_actualizacion = True
        if datos_lead_extracted.get("respondio_fondo"):
            datos_lead["fondo_validado"] = True
            val = datos_lead_extracted.get("nivel_fondo", "")
            datos_lead["nivel_fondo"] = "menor" if "menor" in val.lower() else "mayor"
            hubo_actualizacion = True
        
        # --- CORRECCIÓN CRÍTICA ---
        # Guardamos SIEMPRE. Si el usuario dijo "no tengo info", se guardará con "Pendiente" (gracias a tools.py)
        # pero garantizamos que el registro se cree en el sheet.
        info_final = state["info_cliente"].copy()
        info_final["email"] = email_usuario
        fecha_cita_guardar = state.get("fecha_cita_final")
        
        tools.guardar_lead_sheet(datos_lead, info_final, asesor, fecha_cita_guardar)

        # Definimos la despedida según lo que pasó
        if hubo_actualizacion:
            instruccion = "[SISTEMA] Datos recibidos. Agradece, recuerda la fecha y despídete."
        elif analisis.get("es_rechazo"):
            instruccion = "[SISTEMA] El usuario indicó no estar interesado en dar más datos. Despídete amablemente recordando la cita."
        else:
            # Caso: "No tengo información" o "Gracias"
            instruccion = "[SISTEMA] El usuario no tiene la información o se está despidiendo. Dile que no se preocupe, que todo está listo para la cita y despídete."

        return {
            "conversation_status": "finished",
            "datos_lead": datos_lead,
            "motivo_rechazo": motivo_actualizado,
            "system_context_instruction": instruccion
        }

    # -----------------------------------------------------------------
    # FLUJO PRINCIPAL (Antes de tener cita confirmada)
    # -----------------------------------------------------------------

    # A.1 RECHAZO DEFINITIVO
    if analisis.get("es_rechazo"):
        motivo_final = motivo_actualizado if motivo_actualizado else "Desinterés"
        tools.guardar_no_interesado_sheet(state["info_cliente"], motivo_final)
        return {
            "conversation_status": "finished",
            "motivo_rechazo": motivo_final,
            "system_context_instruction": "El usuario rechazó tajantemente. Despídete."
        }
    
    # A.2 OBJECIÓN RECUPERABLE (Estrategia Persuasión)
    if analisis.get("es_objecion_recuperable"):
        contexto_extra = (
            "\n[SISTEMA] EL USUARIO TIENE DUDAS. NO CIERRES EL CHAT.\n"
            "INSTRUCCIÓN: Aplica la 'ESTRATEGIA DE RECUPERACIÓN'. Invítalo a vivir la experiencia Jelpit."
        )
        # Nota: No cambiamos status a 'finished', dejamos que continue.

    # B. ACTUALIZAR DATOS (Recolección pasiva)
    datos_lead_extracted = analisis.get("datos_lead", {})
    if datos_lead_extracted.get("tiene_inmuebles"):
        datos_lead["inmuebles"] = str(datos_lead_extracted.get("valor_inmuebles"))
    if datos_lead_extracted.get("respondio_fondo"):
        datos_lead["fondo_validado"] = True
        val = datos_lead_extracted.get("nivel_fondo", "")
        datos_lead["nivel_fondo"] = "menor" if "menor" in val.lower() else "mayor"
    
    completos = datos_lead["inmuebles"] and datos_lead["fondo_validado"]

    # C. FECHAS
    intencion_fecha = analisis.get("intencion_fecha", {})
    nueva_fecha_detectada = False
    
    if intencion_fecha.get("menciona_fecha"):
        fecha_iso = intencion_fecha.get("fecha_iso")
        if fecha_iso:
            fecha_contexto = fecha_iso
            nueva_fecha_detectada = True
            esperando_email = False 
            fecha_final_cita = None
            if not asesor: asesor = tools.seleccionar_mejor_asesor(datos_lead)
            msg_cupos, slots = tools.obtener_cupos_por_fecha(fecha_contexto, asesor)
            
            try:
                dt_obj = datetime.strptime(fecha_iso, "%Y-%m-%d")
                dias_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
                fecha_texto_claro = f"{dias_es[dt_obj.weekday()]} {dt_obj.day}"
            except: fecha_texto_claro = fecha_iso

            # --- MENSAJES PERSONALIZADOS (DOMINGO/FESTIVO) ---
            if msg_cupos.startswith("ES FESTIVO"):
                contexto_extra = (
                    f"\n[SISTEMA: La fecha {fecha_texto_claro} es FESTIVO]. "
                    f"INSTRUCCIÓN OBLIGATORIA: Di textualmente: 'Te cuento que justo esa fecha es festivo 🇨🇴 y nuestro equipo hará una pequeña pausa para recargar baterías 🔋.' "
                    f"Luego pregunta qué otro día le queda bien."
                )
                fecha_contexto = None
            elif "DOMINGO" in msg_cupos:
                contexto_extra = (
                    f"\n[SISTEMA: La fecha {fecha_texto_claro} es DOMINGO]. "
                    f"INSTRUCCIÓN OBLIGATORIA: Di textualmente: 'Te cuento que los domingos nuestro equipo toma un pequeño respiro para recargar energías 🔋 y volver con toda la actitud.' "
                    f"Luego pregunta qué otro día le queda bien."
                )
                fecha_contexto = None
            elif msg_cupos == "AGENDA LLENA":
                contexto_extra = f"\n[SISTEMA: Agenda llena para {fecha_texto_claro}. Pide otra fecha.]"
                fecha_contexto = None
            elif msg_cupos.startswith("Error"):
                contexto_extra = "\n[SISTEMA: Error técnico. Pide disculpas.]"
                fecha_contexto = None
            else:
                contexto_extra = f"\n[SISTEMA: Cupos para {fecha_texto_claro}]: \n{msg_cupos}\nINSTRUCCIÓN: Ofrece los horarios."

    # D. CONFIRMACIÓN EMAIL Y CREACIÓN CITA
    info_email = analisis.get("confirmacion_email", {})
    regex_detected = analisis.get("regex_detected", False)
    
    if esperando_email and not nueva_fecha_detectada:
        confirmado = False
        
        if regex_detected:
            confirmado = True
        elif info_email.get("es_confirmacion"):
            confirmado = True
            
        if confirmado and fecha_final_cita:
            # CREAR EVENTO
            evt = tools.crear_evento_calendar(asesor, email_usuario, state["info_cliente"]["nombre"], fecha_final_cita)
            
            if evt:
                info_final = state["info_cliente"].copy()
                info_final["email"] = email_usuario
                cita_agendada_data = evt
                
                # --- LÓGICA DE GUARDADO CONDICIONAL ---
                if completos:
                    # CASO 1: YA TENEMOS TODO -> Guardamos YA y nos despedimos.
                    tools.guardar_lead_sheet(datos_lead, info_final, asesor, fecha_final_cita)
                    status = "finished"
                    contexto_extra = f"[SISTEMA] Cita creada ID {evt['id']}. Despídete confirmando el envío a {email_usuario}."
                else:
                    # CASO 2: FALTAN DATOS -> NO GUARDAMOS EN SHEETS TODAVÍA.
                    # Mantenemos el chat abierto para intentar capturar los datos en el siguiente turno.
                    status = "continue"
                    contexto_extra = (
                        f"\n[SISTEMA: ✅ Cita creada EXITOSAMENTE en Calendar]. "
                        f"INSTRUCCIÓN OBLIGATORIA (NO TE DESPIDAS): "
                        f"1. Confirma la cita y el envío a {email_usuario}. "
                        f"2. Di textualmente: 'Por cierto, antes de terminar, para completar tu perfil: ¿Cuántos inmuebles tiene el conjunto y el fondo de imprevistos supera los 45M?'"
                    )
                
                esperando_email = False
                fecha_contexto = None
            else:
                contexto_extra = "\n[SISTEMA: Error creando cita (Calendar). Pide intentar de nuevo.]"
        else:
             contexto_extra = (
                 f"\n[SISTEMA: Debes confirmar el correo]. "
                 f"PREGUNTA: '¿Confirmo la cita con tu correo {email_usuario} o prefieres otro?'"
             )

    # E. SELECCIÓN DE HORA
    intencion_hora = analisis.get("intencion_hora", {})
    if fecha_contexto and not nueva_fecha_detectada and not esperando_email:
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
            except: pass

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
                    f"\n[SISTEMA: Hora {hora_valida} reservada]. "
                    f"INSTRUCCIÓN: '¡Perfecto! La sesión queda agendada para... "
                    f"¿Confirmo la cita con tu correo {email_usuario} o prefieres otro?'"
                )
            else:
                contexto_extra = f"\n[SISTEMA: Hora {hora_simple} ocupada. Disponibles: {slots_reales}]. Ofrece las disponibles."

    return {
        "datos_lead": datos_lead,
        "fecha_cita_potencial": fecha_contexto,
        "asesor_asignado": asesor,
        "email_usuario": email_usuario,
        "esperando_confirmacion_email": esperando_email,
        "fecha_cita_final": fecha_final_cita,
        "conversation_status": status,
        "cita_agendada": cita_agendada_data, 
        "motivo_rechazo": motivo_actualizado, 
        "system_context_instruction": contexto_extra
    }

def generar_respuesta(state: LiaState):
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    system_instr = utils.generar_system_instruction(state["info_cliente"].get("nombre", "Usuario"))
    contexto_sistema = state.get("system_context_instruction", "")
    gemini_msgs = []
    for m in state["messages"]:
        gemini_msgs.append(types.Content(role=m["role"], parts=[types.Part.from_text(text=str(m["parts"][0]))]))
    if contexto_sistema: gemini_msgs[-1].parts[0].text += f"\n{contexto_sistema}"
    
    config = types.GenerateContentConfig(temperature=0.3, max_output_tokens=1024, system_instruction=system_instr)
    try:
        resp = client.models.generate_content(model="gemini-2.0-flash-lite-001", contents=gemini_msgs, config=config)
        text_resp = resp.text.replace("```", "").strip()
    except: text_resp = "Error de conexión."
    
    return {"messages": [{"role": "model", "parts": [text_resp]}], "system_context_instruction": ""}

workflow = StateGraph(LiaState)
workflow.add_node("analizar", analizar_input)
workflow.add_node("logica", gestionar_logica)
workflow.add_node("generar", generar_respuesta)
workflow.add_edge(START, "analizar")
workflow.add_edge("analizar", "logica")
workflow.add_edge("logica", "generar")
workflow.add_edge("generar", END)
app_graph = workflow.compile()