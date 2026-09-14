"""
Parche mínimo para poder importar `scrapegraphai` con las versiones actuales
de langchain-community (ver scrapegraph_adapter.py para el porqué completo
de que exista este archivo -- no es capricho).

langchain-community está en proceso de "sunset" (aviso de deprecación del
propio paquete) y ya retiró `ChatOllama` de `langchain_community.chat_models`
-- pero scrapegraphai (1.76.0, la versión publicada al 14/09/2026) todavía
hace `from langchain_community.chat_models import ChatOllama` a nivel de
módulo dentro de uno de sus nodos internos. Sin este parche, ni siquiera se
puede hacer `import scrapegraphai` -- revienta con ImportError, aunque este
proyecto nunca use Ollama (usamos Gemini).

Este archivo debe importarse ANTES que cualquier cosa de scrapegraphai
(scrapegraph_adapter.py ya lo hace). Si en el futuro scrapegraphai publica
una versión que ya no necesite esto, se puede borrar sin problema -- el
import de scrapegraphai simplemente funcionará solo y este parche queda de
más (no rompe nada si igual se deja).
"""
import langchain_community.chat_models as _chat_models

if not hasattr(_chat_models, "ChatOllama"):

    class _ChatOllamaStub:
        """Nunca se instancia de verdad -- solo existe para que el import de
        scrapegraphai no reviente. Si algún día SÍ se intenta usar Ollama
        como backend del LLM, esto debe fallar fuerte (en vez de fingir que
        funciona) para no confundir sobre por qué no hay respuesta real."""

        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "ChatOllama no está disponible en esta instalación de "
                "langchain-community (la retiraron). Este proyecto usa "
                "Gemini como backend del LLM, no Ollama -- si ves este "
                "error, algo en la configuración del LLM cambió sin querer."
            )

    _chat_models.ChatOllama = _ChatOllamaStub
