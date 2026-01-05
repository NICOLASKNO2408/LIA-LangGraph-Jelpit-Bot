import os
import traceback
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from google.cloud import firestore
from dotenv import load_dotenv

from state import LiaState
from graph import app_graph
import tools

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
try:
    if os.path.exists("service_account.json"):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"
    db = firestore.Client(project=PROJECT_ID)
    print("🔥 Conexión a Firestore EXITOSA.")
except Exception as e:
    print(f"❌ Error conectando a Firestore: {e}")
    db = None

app = FastAPI(title="LIA LangGraph API", version="2.6.0") # Actualizamos versión

class LeadData(BaseModel):
    nombre: str
    email: str
    telefono: str
    conjunto: str

class StartSessionRequest(BaseModel):
    session_id: str
    lead_data: LeadData

class SendMessageRequest(BaseModel):
    session_id: str
    message: str

class RejectRequest(BaseModel):
    lead_data: LeadData
    reason: str = "Clic Botón Inicial - No Interesa"

def get_empty_state() -> LiaState:
    return {
        "messages": [],
        "info_cliente": {},
        "datos_lead": {"inmuebles": None, "fondo_validado": False, "nivel_fondo": None},
        "asesor_asignado": None,
        "fecha_cita_potencial": None,
        "fecha_cita_final": None,
        "email_usuario": "",
        "esperando_confirmacion_email": False,
        "conversation_status": "continue",
        "cita_agendada": None,
        "motivo_rechazo": None,
        "system_context_instruction": None,
        "analisis_temp": None
    }

def load_state_from_firestore(session_id: str) -> LiaState:
    if not db: return get_empty_state()
    doc_ref = db.collection("conversations").document(session_id)
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        state = get_empty_state()
        state.update(data)
        return state
    else:
        return get_empty_state()

def save_state_to_firestore(session_id: str, state: LiaState):
    if not db: return
    
    state_to_save = state.copy()
    if "analisis_temp" in state_to_save:
        del state_to_save["analisis_temp"]
    
    # --- AJUSTE 3: GUARDAR LINK Y ID EN LA RAÍZ DEL DOCUMENTO ---
    if state_to_save.get("cita_agendada"):
        cita = state_to_save["cita_agendada"]
        state_to_save["idMeet"] = cita.get("id")
        state_to_save["meetLink"] = cita.get("meet_link")
    
    state_to_save["updated_at"] = firestore.SERVER_TIMESTAMP
    db.collection("conversations").document(session_id).set(state_to_save, merge=True)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": "JSON Invalido", "errors": str(exc)})

@app.post("/chat/start")
async def start_chat_session(request: StartSessionRequest):
    try:
        state = get_empty_state()
        state["info_cliente"] = request.lead_data.model_dump()
        state["email_usuario"] = request.lead_data.email
        
        # --- AJUSTE 1: SALUDO CONTEXTUAL (JELPIT) ---
        # Este prompt conecta con el botón "Sí, me interesa" de la imagen.
        prompt_arranque = """
        [SISTEMA] El cliente acaba de ver la imagen del portafolio y presionó el botón 'Sí, me interesa'.
        
        TU INSTRUCCIÓN OBLIGATORIA DE INICIO:
        1. NO saludes con "Hola" (ya vienes hablando).
        2. Tu primera frase DEBE SER TEXTUALMENTE (puedes variar emojis): 
           "¡Me encanta que estés interesado! 🌟 Te cuento que *Jelpit* es el ecosistema experto en propiedad horizontal del Banco Davivienda..."
        3. Conecta explicando brevemente que Jelpit agrupa conciliación, pagos y beneficios.
        4. Cierra preguntando: "¿Te gustaría conocer más detalles o prefieres que miremos disponibilidad para una sesión virtual con uno de nuestros agentes especializados?"
        """
        
        state["messages"] = [{"role": "user", "parts": [prompt_arranque]}]
        final_state = app_graph.invoke(state)
        ai_response = final_state["messages"][-1]["parts"][0]
        
        save_state_to_firestore(request.session_id, final_state)
        
        return {
            "response": ai_response,
            "status": final_state["conversation_status"],
            "data": final_state["datos_lead"]
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/message")
async def send_message(request: SendMessageRequest):
    try:
        state = load_state_from_firestore(request.session_id)
        state["messages"].append({"role": "user", "parts": [request.message]})
        
        final_state = app_graph.invoke(state)
        
        last_message = final_state["messages"][-1]
        response_text = last_message["parts"][0] if last_message["role"] == "model" else "..."
            
        save_state_to_firestore(request.session_id, final_state)
        
        return {
            "response": response_text,
            "status": final_state["conversation_status"],
            "data": final_state["datos_lead"]
        }
    except Exception as e:
        traceback.print_exc()
        return {
            "response": "Lo siento, tuve un pequeño lapso de memoria. ¿Me puedes repetir eso?",
            "status": "continue",
            "data": {}
        }

@app.post("/chat/reject")
async def reject_initial(request: RejectRequest):
    try:
        info_cliente = request.lead_data.model_dump()
        tools.guardar_no_interesado_sheet(info_cliente, request.reason)
        return {"status": "rejected", "message": "Rechazo guardado"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    print("🚀 LIA V2.6 (Ajustes Jelpit + DB) INICIANDO...")
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))