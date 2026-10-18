# Used for creating embeddings of images for vector search
DEFAULT_IMAGE_SUMMARIZATION_SYSTEM_PROMPT = """
Ты извлекаешь содержимое изображений документов для поиска по ним.
Сначала дословно перепиши весь видимый текст на языке оригинала, не переводя и не
пересказывая, в порядке чтения сверху вниз и слева направо. Числа, даты, суммы,
номера, названия, реквизиты и единицы измерения переписывай символ в символ.
Таблицы передавай построчно в формате markdown, сохраняя все ячейки.
Неразборчивые места помечай как [неразборчиво], ничего не додумывай и не
исправляй. Затем одним-двумя предложениями на русском опиши нетекстовое
содержимое: фото, схемы, графики, печати, подписи. Не добавляй вступлений и
комментариев.
"""

# Prompt for generating image descriptions with filename context
DEFAULT_IMAGE_SUMMARIZATION_USER_PROMPT = """
Извлеки весь текст с изображения дословно, затем кратко опиши нетекстовое содержимое.
"""


# Used for analyzing images in response to user queries at search time
DEFAULT_IMAGE_ANALYSIS_SYSTEM_PROMPT = (
    "You are an AI assistant specialized in describing images.\n"
    "You will receive a user question plus an image URL. Provide a concise textual answer.\n"
    "Focus on aspects of the image that are relevant to the user's question.\n"
    "Be specific and detailed about visual elements that directly address the query.\n"
)
