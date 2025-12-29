from typing import TypedDict, List, Optional, Annotated, Dict, Any
from operator import add

class LiaState(TypedDict):
    messages: Annotated[List[dict], add] 
    
    info_cliente: Dict[str, Any]
    datos_lead: Dict[str, Any]

    asesor_asignado: Optional[str]
    fecha_cita_potencial: Optional[str]
    fecha_cita_final: Optional[str]

    email_usuario: str
    esperando_confirmacion_email: bool
    conversation_status: str

    cita_agendada: Optional[Dict[str, Any]]
    motivo_rechazo: Optional[str]

    system_context_instruction: Optional[str]

    analisis_temp: Optional[Dict[str, Any]]