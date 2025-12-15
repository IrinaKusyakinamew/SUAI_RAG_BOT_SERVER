from qdrant_client import QdrantClient, models
from qdrant_client.models import Filter, FieldCondition, MatchAny, MatchText
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Any, Set, Optional
import re
import json
import os
import requests

QDRANT_URL = "http://212.192.220.24:6333"
API_KEY = "pii5z%cE1"
COLLECTION = "schedules_embeddings"

DOC_PREFIX = {
    "group": "groups_",  # для групп
    "room": "classrooms_",  # для аудиторий
    "teacher": "teachers_",  # для преподавателей
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
        embed_model = "../model"
        print("Loading embedding model...")
        self.model = SentenceTransformer(embed_model, device="cpu")
        print("Model loaded")
        self.qdrant = QdrantClient(url=qdrant_url, api_key=api_key, timeout=30, prefer_grpc=False)
        print("Qdrant client initialized")
        self.text_collection = "text_embeddings"
        self.schedule_collection = "schedules_embeddings"

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

    # Базовый поиск расписания
    def search_schedule(self, search_type: str, search_value: str, limit=1000):
        # Определяем параметры поиска в зависимости от типа
        if search_type == 'group':
            filter_key = "metadata.groups"
            match_type = MatchAny(any=[search_value])
            doc_prefix = DOC_PREFIX["group"]

        elif search_type == 'room':
            filter_key = "metadata.room"
            clean_value = re.sub(r'^(ауд\.?|аудитория|ауд)\s*', '', search_value.lower()).strip()

            search_patterns = [clean_value]
            if '-' in clean_value:
                search_patterns.append(clean_value.replace('-', ''))
            search_patterns.append(f" {clean_value} ")

            room_conditions = []
            for pattern in search_patterns:
                room_conditions.append(
                    FieldCondition(key=filter_key, match=MatchText(text=pattern))
                )

            match_type = Filter(should=room_conditions)
            doc_prefix = DOC_PREFIX["room"]

        elif search_type == 'teacher':
            filter_key = "metadata.teacher"
            match_type = MatchText(text=search_value)
            doc_prefix = DOC_PREFIX["teacher"]

        else:
            return []

        try:
            if search_type == 'room':
                filter_ = match_type
            else:
                filter_ = Filter(must=[FieldCondition(key=filter_key, match=match_type)])

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

                    if not scroll_result:
                        break

                    points, next_offset = scroll_result

                    if not points:
                        break

                    all_points.extend(points)
                    total_scanned += len(points)

                    if next_offset is None or len(points) == 0:
                        break

                except Exception:
                    break

            points = all_points

            filtered_points = []
            for point in points:
                payload = point.payload or {}
                doc_id = payload.get('document_id', '')

                if doc_id.startswith(doc_prefix):
                    filtered_points.append(point)

            unique_lessons = set()
            lessons = []

            for point in filtered_points:
                payload = point.payload or {}
                metadata = extract_metadata(payload)

                day = metadata.get("day", "")
                time = metadata.get("time", "")
                subject = metadata.get("subject", "")
                week = metadata.get("week", "не указано")
                room = metadata.get("room", "")
                teacher = metadata.get("teacher", [])
                groups = metadata.get("groups", [])

                key = f"{day}|{time}|{subject}|{week}"

                if key not in unique_lessons:
                    unique_lessons.add(key)
                    lessons.append({
                        "day": day,
                        "time": time,
                        "subject": subject,
                        "week": week,
                        "room": room,
                        "teacher": teacher,
                        "groups": groups,
                        "score": 1.0,
                        "payload": metadata
                    })

            day_order = {"Понедельник": 1, "Вторник": 2, "Среда": 3,
                         "Четверг": 4, "Пятница": 5, "Саббота": 6}
            time_order = {"1 пара": 1, "2 пара": 2, "3 пара": 3,
                          "4 пара": 4, "5 пара": 5, "6 пара": 6}

            lessons.sort(key=lambda x: (day_order.get(x["day"], 99), time_order.get(x["time"], 99)))

            return lessons

        except Exception:
            return []

    def _extract_metadata(self, payload: Dict) -> Dict:
        """Извлекает метаданные из payload"""
        return extract_metadata(payload)

    def detect_query_type(self, query: str) -> Dict[str, Any]:
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

        # 3. Преподаватели - ТОЛЬКО если есть контекст расписания
        if has_schedule_kw or analysis["groups"] or analysis["rooms"] or analysis["days"] or analysis["times"]:
            # Ищем слова с заглавной буквы длиннее 2 букв
            words = original_query.split()
            for word in words:
                clean_word = re.sub(r'[.,!?;:]', '', word)
                if (len(clean_word) > 2 and
                        clean_word[0].isupper() and
                        not clean_word.isdigit() and
                        clean_word.lower() not in days and
                        clean_word.lower() not in schedule_keywords):
                    analysis["teachers"].append(clean_word)

        # Убираем дубликаты
        analysis["teachers"] = list(set(analysis["teachers"]))

        # 4. Определяем тип запроса
        has_schedule_entities = any([
            analysis["groups"],
            analysis["rooms"],
            analysis["days"],
            analysis["times"],
            analysis["teachers"],  # Преподаватели тоже считаем сущностью расписания
        ])

        if has_schedule_kw or has_schedule_entities:
            analysis["is_schedule"] = True
            analysis["type"] = "schedule"
        else:
            analysis["type"] = "general"

        return analysis

    def search_schedule_combined(self, criteria: Dict[str, Any], limit=1000):
        """ Комбинированный поиск по нескольким критериям """
        filters = []

        # Добавляем фильтры для каждого критерия
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

                # Берем только из файлов расписания
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
                         "Четверг": 4, "Пятница": 5, "Суббота": 6}
            time_order = {"1 пара": 1, "2 пара": 2, "3 пара": 3,
                          "4 пара": 4, "5 пара": 5, "6 пара": 6}

            lessons.sort(key=lambda x: (day_order.get(x["day"], 99), time_order.get(x["time"], 99)))

            return lessons

        except Exception:
            return []

    def search_schedule_flexible(self, query: str, criteria: Dict[str, Any], limit=1000):
        """ Гибкий комбинированный поиск по естественному запросу """
        # Если есть конкретные критерии - используем фильтры
        if any([criteria["groups"], criteria["rooms"], criteria["teachers"],
                criteria["days"], criteria["times"]]):
            return self.search_schedule_combined(criteria, limit)

        # Если нет конкретных критериев, но запрос явно о расписании
        # Используем векторный поиск
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

                # Берем только из файлов расписания
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
                        "score": float(point.score),  # Для сортировки по релевантности
                    })

            # Сортировка сначала по дню/времени, потом по релевантности
            day_order = {"Понедельник": 1, "Вторник": 2, "Среда": 3,
                         "Четверг": 4, "Пятница": 5, "Суббота": 6}
            time_order = {"1 пара": 1, "2 пара": 2, "3 пара": 3,
                          "4 пара": 4, "5 пара": 5, "6 пара": 6}

            lessons.sort(key=lambda x: (
                day_order.get(x["day"], 99),
                time_order.get(x["time"], 99),
                -x.get("score", 0)  # По убыванию релевантности
            ))

            return lessons

        except Exception:
            return []

    # Поиск документов
    def search_documents(self, query: str, collection_name: str, top_k: int = 50) -> List[Dict]:
        query_vector = self.model.encode(query, normalize_embeddings=True).tolist()
        try:
            points = self.qdrant.search(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=top_k,
                with_payload=True
            )
            print(f"   Найдено точек: {len(points)}")
            results = []
            for point in points:
                payload = point.payload or {}
                full_payload = self._extract_metadata(payload)
                doc_type = "schedule" if full_payload.get("source") == "schedule" else "general"
                results.append({
                    "id": point.id,
                    "score": float(point.score),
                    "text": full_payload.get("full_text", ""),
                    "type": doc_type,
                    "payload": full_payload
                })
            return results
        except Exception as e:
            print(f" Ошибка поиска в коллекции '{collection_name}': {e}")
            return []

    def _get_collection_for_query(self, query_type: str) -> str:
        return self.schedule_collection if query_type == "schedule" else self.text_collection

    # Фильтрация расписания
    def filter_schedule_results(self, results: List[Dict], analysis: Dict[str, Any]) -> List[Dict]:
        filtered = []
        for result in results:
            if result.get("type") != "schedule":
                continue
            chunk = result.get("payload")
            if not chunk:
                continue

            # Фильтры
            if analysis["groups"]:
                groups_from_chunk = chunk.get("groups", [])
                chunk_groups_clean = []
                for group_item in groups_from_chunk:
                    if isinstance(group_item, str):
                        match = re.search(r'(\d{3,4}[а-ямк]?)', group_item)
                        if match:
                            chunk_groups_clean.append(match.group(1).lower())
                if chunk_groups_clean and not any(g.lower() in chunk_groups_clean for g in analysis["groups"]):
                    continue

            if analysis["teachers"]:
                teachers_from_chunk = chunk.get("teacher", [])
                if isinstance(teachers_from_chunk, list):
                    chunk_teachers_clean = [item.lower() for i, item in enumerate(teachers_from_chunk) if
                                            i % 2 == 0 and isinstance(item, str)]
                    if chunk_teachers_clean and not any(
                            t.lower() in chunk_teachers_clean for t in analysis["teachers"]):
                        continue

            if analysis["rooms"]:
                room_str = str(chunk.get("room", "")).lower()
                if room_str and not any(r in room_str for r in analysis["rooms"]):
                    continue

            if analysis["days"]:
                day_str = str(chunk.get("day", "")).lower()
                if day_str and not any(d.lower() in day_str for d in analysis["days"]):
                    continue

            filtered.append(result)
        return filtered

    # Форматирование расписания (новый метод для работы с search_schedule)
    def format_schedule_from_lessons(self, lessons: List[Dict]) -> str:
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

    # Форматирование расписания (старый метод)
    def format_schedule_response(self, results: List[Dict]) -> str:
        if not results:
            return " Расписание по вашему запросу не найдено."

        day_order = {"Понедельник": 1, "Вторник": 2, "Среда": 3,
                     "Четверг": 4, "Пятница": 5, "Суббота": 6, "Воскресенье": 7}

        def sort_key(result):
            chunk = result["payload"]
            day_num = day_order.get(chunk.get("day", ""), 99)
            time_str = chunk.get("time", "")
            para_match = re.search(r'(\d+)', time_str)
            para_num = int(para_match.group(1)) if para_match else 99
            return (day_num, para_num, -result.get("score", 0))

        results_sorted = sorted(results, key=sort_key)
        output = ["📅 **Расписание**"]
        current_day = None
        entry_number = 1
        for result in results_sorted:
            chunk = result["payload"]
            day = chunk.get("day", "")
            if day != current_day:
                current_day = day
                output.append(f"\n📆 {current_day}:")
                entry_number = 1
            output.append(f"{entry_number}. **{chunk.get('time', '')}**")
            output.append(f"   📚 {chunk.get('subject', '')}")
            room = chunk.get('room', '')
            if room:
                output.append(f"   🏢 Аудитория: {room}")
            teachers = chunk.get('teacher', [])
            if isinstance(teachers, list):
                teacher_names = [item for i, item in enumerate(teachers) if i % 2 == 0 and isinstance(item, str)]
                if teacher_names:
                    output.append(f"   👨‍🏫 Преподаватель: {', '.join(teacher_names)}")
            groups = chunk.get('groups', [])
            if isinstance(groups, list):
                clean_groups = [match.group(1) for group_item in groups if
                                isinstance(group_item, str) and (match := re.search(r'(\d{3,4}[а-ямк]?)', group_item))]
                if clean_groups:
                    output.append(f"   👥 Группы: {', '.join(clean_groups)}")
            week = chunk.get('week', '')
            if week and week != "не указано":
                output.append(f"   📅 Неделя: {week}")
            output.append("")
            entry_number += 1
        output.append("=" * 60)
        output.append(f"📊 Найдено записей: {len(results_sorted)}")
        return "\n".join(output)

    def format_general_response(self, results: List[Dict]) -> str:
        if not results:
            return " Информация по вашему запросу не найдена."
        output = ["📚 **Найдена информация:**", "=" * 60]
        for i, result in enumerate(results[:5], 1):
            text = result["text"]
            preview = text[:200] + "..." if len(text) > 200 else text
            output.append(f"\n{i}. [релевантность: {result['score']:.3f}]")
            output.append(f"   {preview}")
        return "\n".join(output)

    def search_documents_rag(self, query: str, top_k: int = 5) -> List[Dict]:
        """Метод для поиска документов в обеих коллекциях (для RAG)"""
        query_vector = self.model.encode(query, normalize_embeddings=True).tolist()
        all_results = []
        seen_texts = set()

        for coll in [self.schedule_collection, self.text_collection]:
            try:
                results = self.qdrant.search(
                    collection_name=coll,
                    query_vector=query_vector,
                    limit=top_k,
                    with_payload=True,
                )

                for item in results:
                    text = item.payload.get("full_text", item.payload.get("text", ""))
                    if not text or text in seen_texts:
                        continue

                    seen_texts.add(text)
                    all_results.append({
                        "id": item.id,
                        "score": float(item.score),
                        "text": text,
                        "collection": coll,
                    })
            except Exception:
                continue

        all_results.sort(key=lambda x: x["score"], reverse=True)
        return all_results[:top_k]

    def build_context(self, documents: List[Dict]) -> str:
        """Метод для построения контекста из найденных документов"""
        context_parts = []
        for i, doc in enumerate(documents):
            clean_text = re.sub(r"<\[document\]>|\[document\]>", "", doc["text"])
            clean_text = re.sub(r"\s+", " ", clean_text).strip()[:1000]
            context_parts.append(f"[Документ {i + 1}]: {clean_text}")
        return "\n".join(context_parts)

    def generate_llm_answer(self, question: str, context: str) -> str:
        """Генерация ответа с помощью LLM"""
        if not self.has_llm:
            return "LLM не инициализирован. Используйте обычный режим поиска."
        return self.llm.generate_answer(question, context)

    def _process_general_with_llm(self, query: str) -> Dict[str, Any]:
        """Обработка общих вопросов с LLM"""
        docs = self.search_documents_rag(query, top_k=8)
        context = self.build_context(docs)
        llm_answer = self.llm.generate_answer(query, context)

        return {
            "query": query,
            "type": "general_llm",
            "results_count": len(docs),
            "formatted_results": f"🤖 ОТВЕТ:\n{llm_answer}\n\n📚 Использовано источников: {len(docs)}",
            "message": f"Ответ сгенерирован на основе {len(docs)} документов",
        }

    # Основной метод
    def process_query(self, query: str, use_llm_for_general: bool = True) -> Dict[str, Any]:
        analysis = self.detect_query_type(query)

        print(f"🔍 Анализ запроса: {analysis}")

        # ОБРАБОТКА ЗАПРОСОВ РАСПИСАНИЯ
        if analysis["type"] == "schedule":
            # Проверяем, есть ли реальные критерии для поиска расписания
            has_real_criteria = any([
                analysis["groups"],
                analysis["rooms"],
                analysis["teachers"],
                analysis["days"],
                analysis["times"],
            ])

            if has_real_criteria:
                # Используем гибкий поиск для расписания
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
            else:
                # Нет конкретных критериев, но есть слова расписания
                # Это может быть общий вопрос о расписании
                if use_llm_for_general and self.has_llm:
                    return self._process_general_with_llm(query)
                else:
                    return {
                        "query": query,
                        "type": "general",
                        "results_count": 0,
                        "formatted_results": "Пожалуйста, уточните запрос. Например: 'расписание группы 4318'",
                        "message": "Не удалось определить параметры поиска",
                    }

        # Обработка общих вопросов
        else:
            if use_llm_for_general and self.has_llm:
                return self._process_general_with_llm(query)
            else:
                target_collection = self.text_collection
                all_results = self.search_documents(query, target_collection, top_k=10)
                filtered_results = sorted(all_results, key=lambda x: x["score"], reverse=True)[:5]
                results_count = len(filtered_results)
                formatted_results = self.format_general_response(filtered_results)

                return {
                    "query": query,
                    "type": "general",
                    "results_count": results_count,
                    "formatted_results": formatted_results,
                    "message": f"Найдено {results_count} записей" if results_count > 0 else "Ничего не найдено",
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

        self.base_url = "https://caila.io/api/mlpgate/account/just-ai/model/openai-proxy/predict-with-config"

    def generate_answer(self, question: str, context: str) -> str:
        prompt = f"""Ты — помощник университетского бота. Отвечай ТОЛЬКО на основе предоставленного контекста.
        Контекст: {context}
        Вопрос: {question}
        Дай точный и понятный ответ на русском языке."""

        headers = {
            "MLP-API-KEY": self.api_key,
            "Content-Type": "application/json; charset=utf-8",
        }

        payload = {
            "data": {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are a helpful university assistant."},
                    {"role": "user", "content": prompt},
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
                proxies={"http": None, "https": None},
            )

            if response.status_code != 200:
                return f"Ошибка API: {response.status_code}"

            data = response.json()
            if "choices" in data:
                return data["choices"][0]["message"]["content"]
            elif "data" in data and "choices" in data["data"]:
                return data["data"]["choices"][0]["message"]["content"]
            else:
                return "Не удалось получить ответ от ИИ"

        except Exception as e:
            return f"Ошибка запроса: {str(e)}"


if __name__ == "__main__":
    bot = UniversityBot(
        qdrant_url="http://212.192.220.24:6333",
        api_key="pii5z%cE1",
        llm_api_key="1000097868.198240.pKeMJ9397Eh0C2Ish703JfH2InBrylvoVg5cKHX1"
    )

    test_queries = [
        "4318 расписание",  # Группа
        "ауд 52-17",  # Аудитория
        "расписание Раскопина",  # Преподаватель
        "Боженко расписание на пн",
        "3 пара 4318",  # Комбинированный запрос
        "Как получить стипендию?",  # Общий вопрос
        "Какие документы нужны для поступления?",  # Общий вопрос
        "Когда зимняя сессия?",  # Общий вопрос
    ]

    for i, query in enumerate(test_queries, 1):
        print(f"ТЕСТ {i}: {query}")
        print(f"{'=' * 70}")

        result = bot.process_query(query, use_llm_for_general=True)

        print(f"Тип запроса: {result['type']}")
        print(f"Найдено: {result['results_count']}")
        print(f"\n{result['formatted_results']}")
        print(f"\n💡 {result['message']}")