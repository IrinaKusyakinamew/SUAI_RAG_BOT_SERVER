from qdrant_client import QdrantClient, models
from qdrant_client.models import Filter, FieldCondition, MatchAny, MatchText
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Any, Set, Optional
import re
import json
import os
import requests

DOC_PREFIX = {
    "group": "groups_",
    "room": "classrooms_",
    "teacher": "teachers_",
}


def extract_metadata(payload: dict) -> dict:
    """Извлекает metadata из payload"""
    metadata = payload.get("metadata", {})
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except:
            metadata = {}
    result = payload.copy()
    result.update(metadata)
    if "metadata" in result:
        del result["metadata"]
    return result


class UniversityBot:
    def __init__(self, qdrant_url: str, api_key: str, llm_api_key: str = None):
        embed_model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        print("Loading embedding model...")
        self.model = SentenceTransformer(embed_model, device="cpu")
        print("Model loaded")
        self.qdrant = QdrantClient(url=qdrant_url, api_key=api_key, timeout=30, prefer_grpc=False)
        print("Qdrant client initialized")
        self.text_collection = "text_embeddings"
        self.schedule_collection = "schedules_embeddings"

        # Проверяем коллекции
        self._check_collections()

        # Инициализация LLM для общих вопросов
        if llm_api_key:
            self.llm = LLMGenerator(
                provider="caila",
                api_key=llm_api_key,
                model="gpt-4o-mini",
                temperature=0.1
            )
            self.has_llm = True
        else:
            self.has_llm = False
            print("LLM не инициализирован. Общие вопросы будут обрабатываться без генерации.")

    def _check_collections(self):
        """Проверяет доступность коллекций"""
        try:
            collections = self.qdrant.get_collections()
            for coll in [self.text_collection, self.schedule_collection]:
                found = False
                for collection in collections.collections:
                    if collection.name == coll:
                        info = self.qdrant.get_collection(coll)
                        print(f"✓ Коллекция '{coll}': {info.points_count} записей")
                        found = True
                        break
                if not found:
                    print(f"⚠ Коллекция '{coll}' не найдена")
        except Exception as e:
            print(f"Ошибка при проверке коллекций: {e}")

    # ========== ФУНКЦИИ ДЛЯ РАСПИСАНИЯ ==========

    def detect_query_type(self, query: str) -> Dict[str, Any]:
        """Определяет тип запроса: расписание или общий вопрос"""
        original_query = query
        query_lower = query.lower().strip()

        analysis = {
            "type": "general",
            "is_schedule": False,
            "groups": [],
            "rooms": [],
            "teachers": [],
            "days": [],
            "times": [],
            "original_query": original_query,
        }

        # 1. Проверяем явные признаки расписания
        schedule_keywords = ["расписание", "пара", "пары", "аудитория", "ауд",
                             "лекция", "занятие", "семинар", "практика"]
        has_schedule_kw = any(kw in query_lower for kw in schedule_keywords)

        # 2. Ищем конкретные сущности расписания
        # Группы
        group_matches = re.findall(r'\b\d{3,4}[а-ямк]?\b', query_lower)
        if group_matches:
            analysis["groups"] = list(set(group_matches))

        # Аудитории (номера с дефисом)
        room_matches = re.findall(r'\b\d+-\d+\b', query)
        if room_matches:
            analysis["rooms"] = room_matches

        # Дни недели
        days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота"]
        for day in days:
            if day in query_lower:
                analysis["days"].append(day.capitalize())

        # Пары
        for i in range(1, 7):
            if f"{i} пара" in query_lower or f"{i}-я пара" in query_lower:
                analysis["times"].append(f"{i} пара")

        # 3. Преподаватели
        if has_schedule_kw or analysis["groups"] or analysis["rooms"] or analysis["days"] or analysis["times"]:
            words = original_query.split()
            for word in words:
                clean_word = re.sub(r'[.,!?;:]', '', word)
                if (len(clean_word) > 2 and
                        clean_word[0].isupper() and
                        not clean_word.isdigit() and
                        clean_word.lower() not in days and
                        clean_word.lower() not in schedule_keywords):
                    analysis["teachers"].append(clean_word)

        analysis["teachers"] = list(set(analysis["teachers"]))

        # 4. Определяем тип запроса
        has_schedule_entities = any([
            analysis["groups"],
            analysis["rooms"],
            analysis["days"],
            analysis["times"],
            analysis["teachers"],
        ])

        if has_schedule_kw or has_schedule_entities:
            analysis["is_schedule"] = True
            analysis["type"] = "schedule"
        else:
            analysis["type"] = "general"

        return analysis

    def search_schedule_flexible(self, query: str, criteria: Dict[str, Any], limit=1000):
        """Поиск расписания"""
        # Если есть конкретные критерии - используем фильтры
        if any([criteria["groups"], criteria["rooms"], criteria["teachers"],
                criteria["days"], criteria["times"]]):
            return self._search_schedule_with_filters(criteria, limit)

        # Если нет конкретных критериев, но запрос явно о расписании
        query_vector = self.model.encode(query, normalize_embeddings=True).tolist()

        try:
            results = self.qdrant.search(
                collection_name=self.schedule_collection,
                query_vector=query_vector,
                limit=limit,
                with_payload=True,
            )

            lessons = []
            seen_keys = set()

            for point in results:
                payload = point.payload or {}
                doc_id = payload.get('document_id', '')

                if not doc_id.startswith(('groups_', 'classrooms_', 'teachers_')):
                    continue

                metadata = extract_metadata(payload)

                day = metadata.get("day", "")
                time = metadata.get("time", "")
                subject = metadata.get("subject", "")
                week = metadata.get("week", "не указано")

                key = f"{day}|{time}|{subject}|{week}"

                if key not in seen_keys:
                    seen_keys.add(key)
                    lessons.append({
                        "day": day,
                        "time": time,
                        "subject": subject,
                        "week": week,
                        "room": metadata.get("room", ""),
                        "teacher": metadata.get("teacher", []),
                        "groups": metadata.get("groups", []),
                        "score": float(point.score),
                    })

            # Сортировка
            day_order = {"Понедельник": 1, "Вторник": 2, "Среда": 3,
                         "Четверг": 4, "Пятница": 5, "Суббота": 6}
            time_order = {"1 пара": 1, "2 пара": 2, "3 пара": 3,
                          "4 пара": 4, "5 пара": 5, "6 пара": 6}

            lessons.sort(key=lambda x: (
                day_order.get(x["day"], 99),
                time_order.get(x["time"], 99),
                -x.get("score", 0)
            ))

            return lessons

        except Exception:
            return []

    def _search_schedule_with_filters(self, criteria: Dict[str, Any], limit=1000):
        """Поиск расписания с фильтрами"""
        filters = []

        if criteria.get("groups"):
            for group in criteria["groups"]:
                filters.append(
                    FieldCondition(key="metadata.groups", match=MatchAny(any=[group]))
                )

        if criteria.get("rooms"):
            for room in criteria["rooms"]:
                clean_value = re.sub(r'^(ауд\.?|аудитория|ауд)\s*', '', room.lower()).strip()
                search_patterns = [clean_value]
                if '-' in clean_value:
                    search_patterns.append(clean_value.replace('-', ''))
                search_patterns.append(f" {clean_value} ")

                room_conditions = []
                for pattern in search_patterns:
                    room_conditions.append(
                        FieldCondition(key="metadata.room", match=MatchText(text=pattern))
                    )

                if room_conditions:
                    if len(room_conditions) > 1:
                        filters.append(Filter(should=room_conditions))
                    else:
                        filters.append(room_conditions[0])

        if criteria.get("teachers"):
            for teacher in criteria["teachers"]:
                filters.append(
                    FieldCondition(key="metadata.teacher", match=MatchText(text=teacher))
                )

        if criteria.get("days"):
            for day in criteria["days"]:
                filters.append(
                    FieldCondition(key="metadata.day", match=MatchText(text=day))
                )

        if criteria.get("times"):
            for time in criteria["times"]:
                filters.append(
                    FieldCondition(key="metadata.time", match=MatchText(text=time))
                )

        if not filters:
            return []

        filter_ = Filter(must=filters)

        try:
            all_points = []
            next_offset = None
            total_scanned = 0

            while total_scanned < limit:
                try:
                    scroll_result = self.qdrant.scroll(
                        collection_name=self.schedule_collection,
                        scroll_filter=filter_,
                        limit=500,
                        offset=next_offset,
                        with_payload=True
                    )

                    if not scroll_result or not scroll_result[0]:
                        break

                    points, next_offset = scroll_result
                    all_points.extend(points)
                    total_scanned += len(points)

                    if next_offset is None:
                        break

                except Exception:
                    break

            # Обработка результатов
            lessons = []
            seen_keys = set()

            for point in all_points:
                payload = point.payload or {}
                doc_id = payload.get('document_id', '')

                if not doc_id.startswith(('groups_', 'classrooms_', 'teachers_')):
                    continue

                metadata = extract_metadata(payload)

                day = metadata.get("day", "")
                time = metadata.get("time", "")
                subject = metadata.get("subject", "")
                week = metadata.get("week", "не указано")

                key = f"{day}|{time}|{subject}|{week}"

                if key not in seen_keys:
                    seen_keys.add(key)
                    lessons.append({
                        "day": day,
                        "time": time,
                        "subject": subject,
                        "week": week,
                        "room": metadata.get("room", ""),
                        "teacher": metadata.get("teacher", []),
                        "groups": metadata.get("groups", []),
                    })

            # Сортировка
            day_order = {"Понедельник": 1, "Вторник": 2, "Среда": 3,
                         "Четверг": 4, "Пятница": 5, "Саббота": 6}
            time_order = {"1 пара": 1, "2 пара": 2, "3 пара": 3,
                          "4 пара": 4, "5 пара": 5, "6 пара": 6}

            lessons.sort(key=lambda x: (day_order.get(x["day"], 99), time_order.get(x["time"], 99)))

            return lessons

        except Exception:
            return []

    def format_schedule_from_lessons(self, lessons: List[Dict]) -> str:
        """Форматирует расписание"""
        if not lessons:
            return " Расписание по вашему запросу не найдено."

        day_order = {"Понедельник": 1, "Вторник": 2, "Среда": 3,
                     "Четверг": 4, "Пятница": 5, "Суббота": 6, "Воскресенье": 7}

        lessons_by_day = {}
        for lesson in lessons:
            day = lesson.get("day", "")
            if day not in lessons_by_day:
                lessons_by_day[day] = []
            lessons_by_day[day].append(lesson)

        output = ["📅 **Расписание**"]

        for day in sorted(lessons_by_day.keys(), key=lambda x: day_order.get(x, 99)):
            output.append(f"\n📆 {day}:")
            day_lessons = lessons_by_day[day]

            time_order = {"1 пара": 1, "2 пара": 2, "3 пара": 3,
                          "4 пара": 4, "5 пара": 5, "6 пара": 6}
            day_lessons.sort(key=lambda x: time_order.get(x.get("time", ""), 99))

            for i, lesson in enumerate(day_lessons, 1):
                output.append(f"\n{i}. **{lesson.get('time', '')}**")
                output.append(f"   📚 {lesson.get('subject', '')}")

                room = lesson.get('room', '')
                if room and room != 'не указано':
                    output.append(f"   🏢 Аудитория: {room}")

                teachers = lesson.get('teacher', [])
                if isinstance(teachers, list) and teachers:
                    teacher_names = [str(t) for t in teachers if isinstance(t, str) and t]
                    if teacher_names:
                        output.append(f"   👨‍🏫 Преподаватель: {', '.join(teacher_names[:2])}")

                groups = lesson.get('groups', [])
                if isinstance(groups, list) and groups:
                    group_names = [str(g) for g in groups if g]
                    if group_names:
                        output.append(f"   👥 Группы: {', '.join(group_names[:3])}")

                week = lesson.get('week', '')
                if week and week != 'не указано':
                    output.append(f"   📅 Неделя: {week}")

        output.append("=" * 60)
        output.append(f"📊 Найдено записей: {len(lessons)}")
        return "\n".join(output)

    # ========== ФУНКЦИИ ДЛЯ ОБЩИХ ВОПРОСОВ (старая работающая версия) ==========

    def search_documents(self, query: str, top_k: int = 10) -> List[Dict]:
        """Поиск документов (старая работающая версия)"""
        query_vector = self.model.encode(query, normalize_embeddings=True).tolist()

        all_results = []
        seen_texts: Set[str] = set()

        # Ищем в обеих коллекциях
        for coll in [self.text_collection, self.schedule_collection]:
            try:
                results = self.qdrant.search(
                    collection_name=coll,
                    query_vector=query_vector,
                    limit=top_k,
                    with_payload=True,
                )

                for item in results:
                    text = item.payload.get("text", "")
                    if not text or text in seen_texts:
                        continue

                    seen_texts.add(text)
                    all_results.append({
                        "id": item.id,
                        "score": float(item.score),
                        "text": text,
                        "collection": coll,
                        "metadata": {
                            k: v for k, v in item.payload.items() if k != "text"
                        },
                    })
            except Exception as e:
                print(f"Ошибка поиска в коллекции '{coll}': {e}")
                continue

        all_results.sort(key=lambda x: x["score"], reverse=True)
        return all_results[:top_k]

    def build_context(self, documents: List[Dict]) -> str:
        """Строит контекст из документов (старая работающая версия)"""
        context_parts = []

        for i, doc in enumerate(documents):
            clean_text = re.sub(r"<\[document\]>|\[document\]>", "", doc["text"])
            clean_text = re.sub(r"\s+", " ", clean_text).strip()

            context_parts.append(
                f"[Документ {i + 1} | коллекция: {doc['collection']} | "
                f"релевантность: {doc['score']:.3f}]\n{clean_text}\n"
            )

        return "\n".join(context_parts)

    # ========== ОСНОВНОЙ МЕТОД ОБРАБОТКИ ==========

    def process_query(self, query: str, use_llm_for_general: bool = True) -> Dict[str, Any]:
        """Основной метод обработки запросов"""
        analysis = self.detect_query_type(query)
        print(f"🔍 Анализ запроса: {analysis}")

        # ОБРАБОТКА ЗАПРОСОВ РАСПИСАНИЯ
        if analysis["type"] == "schedule":
            lessons = self.search_schedule_flexible(query, analysis, limit=300)
            formatted_results = self.format_schedule_from_lessons(lessons)

            if lessons:
                message = f"Найдено {len(lessons)} занятий"
            else:
                message = "Расписание по вашему запросу не найдено"

            return {
                "query": query,
                "type": "schedule",
                "results_count": len(lessons),
                "formatted_results": formatted_results,
                "message": message,
            }

        # ОБРАБОТКА ОБЩИХ ВОПРОСОВ (старая логика)
        else:
            # Используем старый подход из UniversityRAGBot
            docs = self.search_documents(query, top_k=8)

            if not docs:
                return {
                    "query": query,
                    "type": "general",
                    "results_count": 0,
                    "formatted_results": "Информация по вашему запросу не найдена.",
                    "message": "Ничего не найдено",
                }

            # Если есть LLM и разрешено его использование
            if use_llm_for_general and self.has_llm:
                context = self.build_context(docs)
                llm_answer = self.llm.generate_answer(query, context)

                return {
                    "query": query,
                    "type": "general_llm",
                    "results_count": len(docs),
                    "formatted_results": f"🤖 {llm_answer}\n\n📚 Использовано источников: {len(docs)}",
                    "message": f"Ответ сгенерирован на основе {len(docs)} документов",
                }

            # Без LLM - просто показываем найденные документы
            else:
                output = ["📚 **Найдена информация:**", "=" * 60]
                for i, doc in enumerate(docs[:5], 1):
                    text = doc["text"]
                    preview = text[:300] + "..." if len(text) > 300 else text
                    output.append(f"\n{i}. [релевантность: {doc['score']:.3f}]")
                    output.append(f"   {preview}")

                formatted_response = "\n".join(output)

                return {
                    "query": query,
                    "type": "general",
                    "results_count": len(docs),
                    "formatted_results": formatted_response,
                    "message": f"Найдено {len(docs)} документов",
                }


class LLMGenerator:
    def __init__(
            self,
            provider: str = "caila",
            api_key: Optional[str] = None,
            model: str = "gpt-4o-mini",
            temperature: float = 0.1,
    ):
        if provider != "caila":
            raise ValueError(f"Неизвестный провайдер: {provider}")

        self.provider = provider
        self.model = model
        self.temperature = temperature

        self.api_key = api_key or os.getenv("CAILA_API_KEY")
        if not self.api_key:
            raise ValueError("CAILA API key not provided")

        self.author = "just-ai"
        self.service = "openai-proxy"
        self.base_url = (
            f"https://caila.io/api/mlpgate/account/"
            f"{self.author}/model/{self.service}/predict-with-config"
        )

    def generate_answer(self, question: str, context: str) -> str:
        """Старый работающий промпт из UniversityRAGBot"""
        prompt = f"""
Ты — помощник университетского бота.
Отвечай ТОЛЬКО на основе предоставленного
контекста.
Если информации недостаточно — скажи, что нужно обратиться в деканат или профильный отдел.
Не выдумывай факты.

Контекст:
{context}

Вопрос студента:
{question}

Дай структурированный и понятный ответ на русском языке.
"""

        headers = {
            "MLP-API-KEY": self.api_key,
            "Content-Type": "application/json; charset=utf-8",
        }

        payload = {
            "data": {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a helpful university assistant.",
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
            },
            "config": {
                "temperature": self.temperature,
                "max_tokens": 1000,
            },
        }

        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

            response = requests.post(
                self.base_url,
                headers=headers,
                data=body,
                timeout=60,
                proxies={
                    "http": None,
                    "https": None,
                },
            )

            if response.status_code != 200:
                return f"Ошибка API {response.status_code}: {response.text}"

            data = response.json()

            if "choices" in data:
                return data["choices"][0]["message"]["content"]

            if "data" in data and "choices" in data["data"]:
                return data["data"]["choices"][0]["message"]["content"]

            return f"Не удалось получить ответ от ИИ"

        except Exception as e:
            return f"Ошибка запроса: {repr(e)}"