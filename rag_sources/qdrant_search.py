from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Set

class UniversityRAGBot:
    def __init__(self, embed_model: str, qdrant_url: str, api_key: str, collection_name: str):
        self.collection_name = collection_name

        # 1. Инициализация модели эмбеддингов
        print("Loading embedding model...")
        self.model = SentenceTransformer(embed_model)
        print("Model loaded")

        # 2. Подключение к Qdrant
        self.qdrant = QdrantClient(
            url=qdrant_url,
            api_key=api_key,
            timeout=30,
            prefer_grpc=False
        )
        print("Qdrant client initialized")

        # 3. Проверка подключения
        self._check_connection()

    def _check_connection(self):
        try:
            info = self.qdrant.get_collection(self.collection_name)
            print(f"Connected to Qdrant. Points count: {info.points_count}")
        except Exception as e:
            print(f"Qdrant connection error: {e}")

    # Ищем top_k релевантных доков по запросу пользователя
    def search_documents(self, query: str, top_k: int = 5) -> List[Dict]:
        query_vector = self.model.encode(query, normalize_embeddings=True).tolist()
        results = self.qdrant.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=top_k,
            with_payload=True
        )

        documents = []
        # Для удаления дубликатиков
        seen_texts = set()
        for item in results:
            text = item.payload.get("text", "")
            if text in seen_texts:
                continue
            seen_texts.add(text)

            documents.append({
                "id": item.id,
                "score": float(item.score),
                "text": text,
                "metadata": {k: v for k, v in item.payload.items() if k != "text"}
            })
        return documents

    # Создаем контекст для rag из найденных доков
    def build_context(self, documents: List[Dict]) -> str:
        context_parts = []
        for i, doc in enumerate(documents):
            context_parts.append(
                f"[Документ {i + 1}, релевантность: {doc['score']:.3f}]:\n{doc['text']}\n"
            )
        return "\n".join(context_parts)


if __name__ == "__main__":
    EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    COLLECTION_NAME = "text_embeddings"
    QDRANT_URL = "http://212.192.220.24:6333"
    API_KEY = "pii5z%cE1"

    bot = UniversityRAGBot(EMBED_MODEL, QDRANT_URL, API_KEY, COLLECTION_NAME)

    query = "Как подать заявление на материальную помощь?"
    results = bot.search_documents(query, top_k=10)
    context = bot.build_context(results)

    print("Контекст для RAG:")
    print(context)