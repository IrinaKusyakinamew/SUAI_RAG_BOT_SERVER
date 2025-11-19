import json
from qdrant_client import QdrantClient
from qdrant_client.conversions.common_types import VectorParams

#путь к JSONL (ПОМЕНЯТЬ)
jsonl_file_path = r'D:\inf\TP\cursach\embeddings.jsonl'

client = QdrantClient(
    url='http://212.192.220.24:6333',
    api_key='pii5z%cE1'
)
#создание и проверка существования коллекции
collection_name = 'text_embeddings'
collections = [col.name for col in client.get_collections().collections]

if collection_name not in collections:
    print(f"Создаю коллекцию '{collection_name}'...")
    vector_size = 384
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=vector_size, distance='Cosine')
    )
    print(f"Коллекция '{collection_name}' успешно создана.")
else:
    print(f"Коллекция '{collection_name}' уже существует.")

#чтение, подготовка и формирование точек
points = []
with open(jsonl_file_path, 'r', encoding='utf-8') as f:
    for line in f:
        obj = json.loads(line)
        id_ = obj['id']
        text = obj['text']
        embedding = obj['embedding']
        metadata = obj.get('metadata', {})

        payload = {
            'text': text,
            **metadata
        }

        point = {
            "id": id_,
            "vector": embedding,
            "payload": payload
        }
        points.append(point)

#деление на батчи и вставка
batch_size = 1000
total_points = len(points)

for i in range(0, total_points, batch_size):
    batch_points = points[i:i + batch_size]
    try:
        client.upsert(
            collection_name=collection_name,
            points=batch_points
        )
        print(f"Загружено {i + len(batch_points)} / {total_points} точек")
    except Exception as e:
        print(f"Ошибка при загрузке батча с {i} по {i + len(batch_points)}: {e}")

print("Загрузка завершена.")