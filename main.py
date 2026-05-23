import os
import subprocess
import threading
import json
import time
import warnings
import urllib.request
import zipfile
import shutil
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

warnings.filterwarnings("ignore", category=FutureWarning)

try:
    import google.generativeai as genai
except ImportError:
    pass

class DummyResponse:
    def __init__(self, text):
        self.text = text

class BookGeneratorCore:
    def __init__(self, api_key: str, selected_model: str, log_callback):
        genai.configure(api_key=api_key)
        self.log = log_callback
        self.model = genai.GenerativeModel(selected_model)
        self.log(f"Система: Инициализирована модель {selected_model}")

    def _generate_with_retry(self, sys_prompt: str, is_plan=False):
        time.sleep(4.5) 
        max_retries = 6
        
        # Настраиваем safety_settings, чтобы обойти базовые блокировки безопасности
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
        
        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(sys_prompt, safety_settings=safety_settings)
                
                # Пытаемся получить текст. Если ответ заблокирован (finish_reason=8),
                # библиотека выбросит исключение
                text = response.text
                if not text:
                    raise Exception("finish_reason block: empty text")
                return response
                
            except Exception as e:
                error_msg = str(e)
                
                # Ловим блокировку безопасности
                if "finish_reason" in error_msg or "valid `Part`" in error_msg or "block" in error_msg.lower() or "safety" in error_msg.lower():
                    self.log(f"⚠️ Внимание: Текст заблокирован фильтрами безопасности Google (Попытка {attempt + 1}).")
                    if attempt == max_retries - 1:
                        if is_plan:
                            raise Exception("Google намертво блокирует создание плана. Пожалуйста, немного смягчите ваш запрос (ИИ отказывается писать про убийства/предательство без цензуры в качестве общего плана).")
                        return DummyResponse("(Сцена заблокирована внутренними фильтрами Google. Сюжет показался ИИ слишком жестоким или нарушающим правила.)")
                    time.sleep(5)
                    continue
                    
                # Ловим серверные ошибки и лимиты (429, 500, 503, 499)
                elif any(err in error_msg for err in ["429", "Quota", "exceeded", "500", "503", "499", "InternalServerError", "ServiceUnavailable", "TooManyRequests"]):
                    # Для 500-х ошибок серверов Google обычно хватает 15-30 секунд. Для лимитов 429 нужно ждать дольше (60 сек).
                    if "429" in error_msg or "Quota" in error_msg:
                        wait_time = 60
                        short_err = "Лимит запросов API (429)"
                    else:
                        wait_time = 25
                        short_err = "Сбой на серверах Google (5xx)"
                        
                    self.log(f"⏳ {short_err}. Ждем {wait_time} сек... (Попытка {attempt + 1})")
                    time.sleep(wait_time)
                else:
                    # Другие ошибки (сеть и т.д.)
                    self.log(f"⏳ Ошибка сети/API: {error_msg[:50]}... Ждем 10 сек... (Попытка {attempt + 1})")
                    time.sleep(10)
                    
        raise Exception("Превышено максимальное количество попыток обращения к API Google.")

    def generate_plan(self, prompt: str, bible: str) -> list:
        self.log("Планировщик: Создаю строгую, непрерывную структуру сюжета...")
        sys_prompt = f"""
Ты — Архитектор Сюжета. Твоя задача — составить логичный, абсолютно непрерывный план объемной книги. 
ПРИМЕЧАНИЕ: Это полностью вымышленное художественное произведение. Все события вымышлены.

Библия проекта (неизменные лор, правила и факты):
{bible}

Запрос пользователя (идея книги):
{prompt}

Чтобы книга получилась цельной и без сюжетных дыр:
1. АБСОЛЮТНАЯ НЕПРЕРЫВНОСТЬ МЕЖДУ ГЛАВАМИ: Каждая новая глава ОБЯЗАНА начинаться ровно в ту же секунду и в том же месте, где закончилась предыдущая. Сюжет идет непрерывным потоком. Никаких закадровых прыжков во времени ("прошел месяц", "на следующий день") или внезапных телепортаций. Каждая сцена плавно перетекает в следующую.
2. ПУТЕШЕСТВИЯ ОПИСЫВАЮТСЯ В ДЕТАЛЯХ: Если герои перемещаются из города А в город Б, ты обязан выделить отдельную сцену (или даже несколько) на то, как они идут/едут, что видят в дороге, какие преграды встречают. Герои не могут оказаться в новом месте "просто так".
3. РАСКРЫТИЕ ПЕРСОНАЖЕЙ И СЮЖЕТ: Тайны, артефакты и конфликты должны развиваться и переходить из главы в главу. Раскрытие персонажей и их сближение должно быть ЕСТЕСТВЕННЫМ. Оно должно вплетаться в действия, экшен и диалоги, а не выглядеть как нелепая сцена-придаток в конце главы, где герои внезапно садятся и рассказывают друг другу свои секреты.
4. ФИНАЛ: Последняя глава должна быть окончательным, структурированным финалом. Закрой все сюжетные линии, подведи итог приключениям героев, создай мощную развязку. Никаких обрывов повествования "на полуслове".
5. Разбей каждую главу на 4-6 последовательных сцен. Каждая сцена — это логическое продолжение предыдущей.

Ответь строго в формате JSON: массив объектов, где каждый объект имеет поля:
"title" - название главы (строка),
"scenes" - массив строк (от 4 до 6 сцен на главу). В каждой строке четко описывай: где именно находятся герои, откуда они пришли, что делают сейчас и куда направляются.

Напиши минимум 7-10 глав.
Верни ТОЛЬКО валидный JSON. Никакого дополнительного текста или форматирования markdown (без ```json).
"""
        response = self._generate_with_retry(sys_prompt, is_plan=True)
        text = response.text.strip()
        
        if text.startswith("```json"):
            text = text[7:-3].strip()
        elif text.startswith("```"):
            text = text[3:-3].strip()
            
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            self.log("Ошибка парсинга JSON. Пытаюсь восстановить...")
            start = text.find('[')
            end = text.rfind(']') + 1
            if start != -1 and end != -1:
                return json.loads(text[start:end])
            raise ValueError(f"Не удалось распознать JSON:\n{text}")

    def write_chapter(self, prompt: str, bible: str, global_plan_text: str, chapter_title: str, scenes: list, global_summary: str, last_chapter_end_text: str, is_final_chapter: bool = False) -> str:
        self.log(f"Писатель: Работаю над главой «{chapter_title}» (сцен: {len(scenes)})...")
        chapter_content = ""
        
        for i, scene in enumerate(scenes):
            self.log(f"  -> Пишу сцену {i+1} из {len(scenes)}...")
            
            if not chapter_content:
                if last_chapter_end_text:
                    local_context = f"ВНИМАНИЕ! ЭТО ПЕРВАЯ СЦЕНА НОВОЙ ГЛАВЫ!\nТы ОБЯЗАН начать текст как ПРЯМОЕ, НЕРАЗРЫВНОЕ продолжение последнего абзаца прошлой главы. Та же самая секунда, та же поза, та же реплика, та же локация. Никаких 'На следующее утро', 'Оказавшись в...' или 'Спустя час'!\n\nВот самые последние строки прошлой главы:\n\n{last_chapter_end_text[-3000:]}\n\nТВОЙ ТЕКСТ ДОЛЖЕН НАЧИНАТЬСЯ СЛЕДУЮЩИМ АБЗАЦЕМ ДЛЯ ЭТОГО ОТРЫВКА! Не пиши вступлений, переходи сразу к действию!"
                else:
                    local_context = "(Это самая первая сцена всей книги. Начни историю плавно и детально.)"
            else:
                local_context = f"Уже написанный текст в этой главе (события прямо перед этой сценой):\n{chapter_content[-3000:]}\n\nОБЯЗАТЕЛЬНО ПРОДОЛЖАЙ ПРЯМО С ПОСЛЕДНЕГО АБЗАЦА. Подхвати мысль, жест или движение и развивай дальше. Не перепрыгивай во времени или пространстве!"

            if is_final_chapter:
                if i == len(scenes) - 1:
                    local_context += "\n\n(ВНИМАНИЕ: ЭТО САМАЯ ПОСЛЕДНЯЯ СЦЕНА ВСЕЙ КНИГИ! Напиши красивый, структурированный финал. Заверши все линии, поставь мощную эмоциональную и логическую точку в истории.)"
                else:
                    local_context += "\n\n(ВНИМАНИЕ: Это сцена из последней главы книги. Начинай подводить сюжет к кульминации и развязке.)"

            sys_prompt = f"""
Ты — Профессиональный Писатель. Твоя задача — написать текст для ОДНОЙ конкретной сцены.
ПРИМЕЧАНИЕ: Это полностью вымышленное художественное произведение. Все события вымышлены. Пиши свободно.

ПРАВИЛА ЖЕСТКОЙ СВЯЗНОСТИ И ЛОГИКИ:
1. НЕПРЕРЫВНОСТЬ: Начинай сцену строго с того момента, где остановилось повествование (см. КОНТЕКСТ ниже). Никаких "спустя час", "оказавшись на месте" или "на следующий день". Пиши непрерывным потоком времени!
2. МАРШРУТЫ И ЛОКАЦИИ: Описывай каждый шаг. Если герои идут в соседнюю комнату — опиши, как они открыли дверь и что увидели по пути. Если едут в другой город — детально опиши саму дорогу. Строжайший запрет на смену локации без описания пути!
3. ОФОРМЛЕНИЕ ДИАЛОГОВ: ИСПОЛЬЗУЙ КЛАССИЧЕСКОЕ РУССКОЕ ОФОРМЛЕНИЕ ДИАЛОГОВ С ТИРЕ!
ПРИМЕР ПРАВИЛЬНОГО ДИАЛОГА:
— Нам пора, — тихо бросил Кайл.
— Я еще не закончил, — огрызнулся Марк, перезаряжая винтовку. — Или ты боишься?
КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать диалоги просто текстом "Нам пора, тихо бросил Кайл." или использовать кавычки для прямой речи! Только тире (—) в начале реплики и перед словами автора!
4. ЛОГИКА ПЕРСОНАЖЕЙ: Сближение и раскрытие героев должно быть ЕСТЕСТВЕННЫМ. Не пиши нелепых сцен, где герои ни с того ни с сего начинают изливать душу. Раскрывай их характеры через ПОСТУПКИ, мелкие жесты, помощь в бою, короткие колкие фразы. Эмоции должны быть оправданы ситуацией.
5. ОБЪЕМ: Раздувай текст художественными приемами. Описывай запахи, звуки, мысли, делай длинные, живые диалоги.

Библия проекта:
{bible}

Глобальный план всей книги (ты сейчас пишешь только одну сцену из него):
{global_plan_text}

Подробная выжимка всех ПРОШЛЫХ глав (обрати особое внимание на конец выжимки, там описано, где именно сейчас находятся герои и что у них есть!):
{global_summary if global_summary else 'Это самое начало истории. Герои находятся там, где начинается первая сцена.'}

Название текущей главы: {chapter_title}
Описание сцены, которую тебе нужно написать сейчас (интегрируй это плавно в повествование):
"{scene}"

КОНТЕКСТ ДЛЯ НАЧАЛА СЦЕНЫ (ЭТО САМОЕ ВАЖНОЕ):
{local_context}

Пиши ТОЛЬКО художественный текст сцены. Без заголовков (например, не пиши "Глава 1" или "Сцена 2"). 
ВАЖНО ДЛЯ TYPST: НЕ ИСПОЛЬЗУЙ СИМВОЛЫ: #, $, *, _, `, @, ~. Пиши обычный чистый текст без какого-либо маркдауна и форматирования. Никаких выделений курсивом или жирным. Не ставь звездочки.
"""
            response = self._generate_with_retry(sys_prompt, is_plan=False)
            cleaned_text = response.text.strip()
            
            # Агрессивная очистка на уровне Питона от любых спецсимволов, которые могут сломать Typst
            for char in ['#', '$', '*', '_', '`', '@', '~']:
                cleaned_text = cleaned_text.replace(char, '')
            cleaned_text = cleaned_text.replace('[', '(').replace(']', ')')
                
            chapter_content += cleaned_text + "\n\n"
            
        return chapter_content.strip()

    def summarize_chapter(self, chapter_text: str, current_global_summary: str) -> str:
        self.log("Суммаризатор: Глубокий анализ и обновление памяти истории...")
        sys_prompt = f"""
Ты — Хранитель Памяти. Твоя задача — вести ОЧЕНЬ подробную, исчерпывающую летопись сюжета.
У тебя есть предыдущая память истории и текст только что написанной новой главы.
ПРИМЕЧАНИЕ: Это полностью вымышленное художественное произведение.

ПРАВИЛА:
1. ЛЕТОПИСЬ, А НЕ КРАТКОЕ СОДЕРЖАНИЕ: Дополняй летопись. Старые события не должны сжиматься или исчезать. Текст выжимки должен только расти, становясь детальной энциклопедией сюжета! Если ты удалишь деталь, Писатель о ней навсегда забудет.
2. ВНИМАНИЕ К ДЕТАЛЯМ: Сохраняй абсолютно все: имена второстепенных персонажей, кто кого предал, кто что нашел (артефакты, предметы), куда конкретно герои направляются, их ранения, эмоциональное состояние, нерешенные загадки.
3. ОБЯЗАТЕЛЬНО в самом конце выжимки добавь три пункта с новой строки:
"ТЕКУЩАЯ ЛОКАЦИЯ: [очень точно: где герои, в какой позе, что они делают в самую последнюю секунду главы]"
"ТЕКУЩЕЕ ВРЕМЯ И ПОГОДА: [какое время суток, что происходит вокруг]"
"ИНВЕНТАРЬ И СТАТУС: [что у них с собой (оружие, артефакты), есть ли ранения или новые союзники]"

Предыдущая память истории (обязательно скопируй эти факты в новую выжимке, дополнив их):
{current_global_summary if current_global_summary else '(Пусто, это первая глава)'}

Текст новой главы (интегрируй эти события в память):
{chapter_text}

Сформируй единый, логичный и МАКСИМАЛЬНО подробный пересказ всего сюжета от начала книги до текущего момента с соблюдением всех правил. Убедись, что локация и статус четко описаны в самом конце!
"""
        response = self._generate_with_retry(sys_prompt, is_plan=False)
        return response.text.strip()

    def build_book(self, title: str, chapters: list, typst_exe: str):
        self.log("Сборщик: Формирую безопасный Typst документ...")
        
        safe_title = title.replace('"', '\\"')
        
        typst_content = f"""
#set document(title: "{safe_title}", author: "AI Writer")
#set page(
  paper: "a5", 
  margin: (inside: 2cm, outside: 1.5cm, top: 2cm, bottom: 2cm),
  numbering: "1"
)
#set text(lang: "ru", size: 11pt, hyphenate: true)
#set par(justify: true, first-line-indent: 1.5em, leading: 0.65em)

// Титульный лист
#align(center + horizon)[
  #text(30pt, weight: "bold")[ {safe_title} ]
  
  #v(3em)
  #text(16pt, style: "italic", fill: luma(80))[Сгенерировано нейросетью]
]
#pagebreak()

// Оглавление
#set text(size: 12pt)
#outline(title: text(18pt, weight: "bold")[Оглавление], depth: 1)
#pagebreak()

// Сброс счетчика страниц для основного текста
#counter(page).update(1)
#set text(size: 11pt)

"""
        for chapter in chapters:
            safe_chap_title = chapter['title'].replace('"', '\\"')
            typst_content += f"""
#align(center)[
  #heading(level: 1)[{safe_chap_title}]
  #v(1.5em)
]
"""
            safe_content = chapter['content']
            # Еще одна прочистка на всякий случай
            for char in ['#', '$', '*', '_', '`', '@', '~']:
                safe_content = safe_content.replace(char, '')
            safe_content = safe_content.replace('[', '(').replace(']', ')')
            
            typst_content += f"{safe_content}\n\n"
            typst_content += "#pagebreak()\n"

        temp_typ = "temp_book.typ"
        temp_pdf = "temp_book.pdf"

        with open(temp_typ, "w", encoding="utf-8") as f:
            f.write(typst_content)

        self.log("Сборщик: Компилирую PDF...")
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            
            result = subprocess.run(
                [typst_exe, "compile", temp_typ, temp_pdf], 
                capture_output=True,
                text=True,
                creationflags=creationflags
            )
            
            if result.returncode == 0:
                self.log(f"Успех! Временный PDF создан.")
                return temp_pdf
            else:
                self.log(f"Ошибка компиляции Typst: {result.stderr}")
                return None
                
        except Exception as e:
            self.log(f"Ошибка вызова Typst: {e}")
            return None


class AppUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Генератор Книг (Gemini + Typst)")
        self.geometry("900x750")
        
        self.api_key_var = tk.StringVar(value=os.getenv("GEMINI_API_KEY", ""))
        self.title_var = tk.StringVar(value="")
        self.model_var = tk.StringVar()
        self.typst_exe = "typst"

        self.create_widgets()
        self.bind_shortcuts()
        self.check_dependencies()

    def bind_shortcuts(self):
        def on_ctrl_key(event):
            if event.keycode == 86:
                self.focus_get().event_generate('<<Paste>>')
            elif event.keycode == 67:
                self.focus_get().event_generate('<<Copy>>')
            elif event.keycode == 88:
                self.focus_get().event_generate('<<Cut>>')
            elif event.keycode == 65:
                self.focus_get().event_generate('<<SelectAll>>')

        self.bind('<Control-KeyPress>', on_ctrl_key)

    def check_dependencies(self):
        try:
            import google.generativeai
        except ImportError:
            messagebox.showwarning("Внимание", "Не найдена библиотека google-generativeai!\nОна нужна для работы.")

    def ensure_typst(self):
        self.log("Проверка наличия компилятора Typst...")
        
        if os.path.exists("typst.exe"):
            self.typst_exe = "typst.exe"
            self.log("Локальный Typst найден.")
            return

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            subprocess.run(["typst", "--version"], capture_output=True, creationflags=creationflags)
            self.typst_exe = "typst"
            self.log("Системный Typst найден.")
            return
        except FileNotFoundError:
            pass

        self.log("Typst не найден. Скачиваю портативную версию...")
        try:
            url = "https://github.com/typst/typst/releases/latest/download/typst-x86_64-pc-windows-msvc.zip"
            zip_path = "typst.zip"
            urllib.request.urlretrieve(url, zip_path)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    if member.endswith("typst.exe"):
                        with zip_ref.open(member) as source, open("typst.exe", "wb") as target:
                            shutil.copyfileobj(source, target)
            if os.path.exists(zip_path):
                os.remove(zip_path)
            self.typst_exe = "typst.exe"
            self.log("Typst успешно установлен!")
        except Exception as e:
            self.log(f"Ошибка скачивания Typst: {e}. Потребуется ручная установка.")

    def load_models(self):
        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showerror("Ошибка", "Сначала введите Gemini API Key!")
            return
            
        self.load_models_btn.config(text="Загрузка...", state=tk.DISABLED)
        
        def fetch():
            try:
                genai.configure(api_key=api_key)
                available = [m.name.replace('models/', '') for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                
                preferred = ['gemini-3.1-flash-lite-preview', 'gemma-4-31b-it', 'gemma-3-27b-it', 'gemini-3.1-pro-preview']
                sorted_models = []
                
                for pref in preferred:
                    if pref in available:
                        sorted_models.append(pref)
                        
                for m in available:
                    if m not in sorted_models:
                        sorted_models.append(m)
                
                self.model_combobox['values'] = sorted_models
                if sorted_models:
                    self.model_combobox.current(0)
                    self.log(f"Модели загружены.")
                else:
                    self.log("Доступных моделей не найдено.")
            except Exception as e:
                self.log(f"Ошибка загрузки моделей: {e}")
            finally:
                self.load_models_btn.config(text="Обновить список моделей", state=tk.NORMAL)
                
        threading.Thread(target=fetch, daemon=True).start()

    def create_widgets(self):
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(top_frame, text="Gemini API Key:").grid(row=0, column=0, sticky=tk.W, pady=2)
        api_entry = ttk.Entry(top_frame, textvariable=self.api_key_var, show="*")
        api_entry.grid(row=0, column=1, sticky=tk.EW, padx=(5, 15), pady=2)
        
        ttk.Label(top_frame, text="Модель:").grid(row=0, column=2, sticky=tk.W, pady=2)
        self.model_combobox = ttk.Combobox(top_frame, textvariable=self.model_var, state="readonly", width=30)
        self.model_combobox.grid(row=0, column=3, sticky=tk.W, padx=5, pady=2)
        
        self.load_models_btn = ttk.Button(top_frame, text="Загрузить модели", command=self.load_models)
        self.load_models_btn.grid(row=0, column=4, sticky=tk.W, pady=2)
        
        ttk.Label(top_frame, text="Название книги:").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Entry(top_frame, textvariable=self.title_var).grid(row=1, column=1, columnspan=4, sticky=tk.EW, padx=(5, 0), pady=2)
        
        top_frame.columnconfigure(1, weight=1)

        mid_frame = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        mid_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        left_pane = ttk.LabelFrame(mid_frame, text="Библия проекта (Лор, правила, константы)")
        self.bible_text = scrolledtext.ScrolledText(left_pane, wrap=tk.WORD, width=40)
        self.bible_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        right_pane = ttk.LabelFrame(mid_frame, text="Запрос (Сюжет и идея конкретной книги)")
        self.prompt_text = scrolledtext.ScrolledText(right_pane, wrap=tk.WORD, width=40)
        self.prompt_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        mid_frame.add(left_pane)
        mid_frame.add(right_pane)

        bottom_frame = ttk.LabelFrame(self, text="Лог работы агентов")
        bottom_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.log_text = scrolledtext.ScrolledText(bottom_frame, wrap=tk.WORD, height=10, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        author_label = ttk.Label(btn_frame, text="Made in BlessedByDiceGod", foreground="gray", font=("Helvetica", 9, "italic"))
        author_label.pack(side=tk.LEFT, padx=10, pady=5)

        self.generate_btn = ttk.Button(btn_frame, text="🚀 Начать генерацию (Много сцен)", command=self.start_generation)
        self.generate_btn.pack(side=tk.RIGHT, ipadx=10, ipady=5)

    def log(self, message: str):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.update_idletasks()

    def start_generation(self):
        try:
            import google.generativeai
        except ImportError:
            messagebox.showerror("Ошибка", "Библиотека google-generativeai не установлена!")
            return

        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showerror("Ошибка", "Введите Gemini API Key!")
            return
            
        selected_model = self.model_var.get().strip()
        if not selected_model:
            messagebox.showerror("Ошибка", "Нажмите 'Загрузить модели' и выберите модель из списка!")
            return
        
        book_title = self.title_var.get().strip()
        if not book_title:
            messagebox.showerror("Ошибка", "Введите название книги!")
            return
            
        self.generate_btn.config(state=tk.DISABLED)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)

        threading.Thread(target=self.run_pipeline, args=(api_key, selected_model), daemon=True).start()

    def run_pipeline(self, api_key, selected_model):
        try:
            self.ensure_typst()
            
            core = BookGeneratorCore(api_key, selected_model, log_callback=self.log)
            bible = self.bible_text.get(1.0, tk.END).strip()
            prompt = self.prompt_text.get(1.0, tk.END).strip()
            book_title = self.title_var.get().strip()

            if not prompt:
                prompt = "Напиши интересную книгу."
                
            plan = core.generate_plan(prompt, bible)
            global_plan_text = json.dumps(plan, ensure_ascii=False, indent=2)
            self.log(f"План готов. Количество глав: {len(plan)}")

            chapters_data = []
            global_summary = ""
            last_chapter_end_text = ""

            for i, chapter_info in enumerate(plan):
                title = chapter_info.get("title", f"Глава {i+1}")
                scenes = chapter_info.get("scenes", [])
                if not scenes:
                    scenes = [chapter_info.get("description", "Развитие сюжета главы.")]

                is_final_chapter = (i == len(plan) - 1)
                
                content = core.write_chapter(prompt, bible, global_plan_text, title, scenes, global_summary, last_chapter_end_text, is_final_chapter)
                chapters_data.append({"title": title, "content": content})
                
                global_summary = core.summarize_chapter(content, global_summary)
                last_chapter_end_text = content
                self.log(f"Глобальная выжимка ВСЕЙ истории до {i+1} главы успешно обновлена.")

            temp_pdf = core.build_book(book_title, chapters_data, self.typst_exe)
            
            if temp_pdf and os.path.exists(temp_pdf):
                self.log("Готово! Выберите, куда сохранить готовую книгу.")
                self.after(0, lambda p=temp_pdf, t=book_title: self.prompt_save_pdf(p, t))

        except Exception as e:
            self.log(f"❌ Произошла ошибка: {e}")
        finally:
            self.after(0, lambda: self.generate_btn.config(state=tk.NORMAL))

    def prompt_save_pdf(self, temp_pdf, book_title):
        safe_filename = "".join(c for c in book_title if c.isalnum() or c in (' ', '-', '_')).strip()
        if not safe_filename:
            safe_filename = "book"
            
        save_path = filedialog.asksaveasfilename(
            parent=self,
            title="Сохранить книгу как",
            initialfile=f"{safe_filename}.pdf",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        
        if save_path:
            try:
                shutil.copy(temp_pdf, save_path)
                self.log(f"Книга успешно сохранена по пути: {save_path}")
                if os.name == 'nt':
                    os.startfile(save_path)
                elif os.name == 'posix':
                    subprocess.call(('open', save_path))
            except Exception as e:
                self.log(f"Ошибка при сохранении файла: {e}")
        else:
            self.log("Сохранение отменено. Временный файл остался в папке программы.")

if __name__ == "__main__":
    app = AppUI()
    app.mainloop()
