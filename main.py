
import json
import math
import threading
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.image import Image
from kivy.storage.jsonstore import JsonStore


BASE_DIR = Path(__file__).resolve().parent

# Подключение шрифта с поддержкой русского языка
FONT_PATH = BASE_DIR / "arial.ttf"

if FONT_PATH.exists():
    LabelBase.register(
        name="Russian",
        fn_regular=str(FONT_PATH)
    )
    FONT = "Russian"
else:
    FONT = "Roboto"


# Русские названия категорий
CATEGORY_NAMES = {
    "Food": "Питание",
    "Transport": "Транспорт",
    "Office": "Офис",
    "Marketing": "Маркетинг",
    "Other": "Другое",
    "Sales": "Продажи",
    "Services": "Услуги",
    "Investments": "Инвестиции",
    "Other Income": "Другие доходы"
}

EXPENSE_CATEGORIES = (
    "Food", "Transport", "Office",
    "Marketing", "Other"
)

INCOME_CATEGORIES = (
    "Sales", "Services",
    "Investments", "Other Income"
)


def translate_category(category):
    return CATEGORY_NAMES.get(category, category)


class ExpenseTrackerApp(App):

    def make_label(self, text, **kwargs):
        return Label(
            text=text,
            font_name=FONT,
            **kwargs
        )

    def make_button(self, text, callback=None):
        button = Button(
            text=text,
            font_name=FONT,
            size_hint_y=None,
            height=42
        )

        if callback:
            button.bind(on_press=callback)

        return button

    def show_message(self, title, message):
        label = self.make_label(
            message,
            halign="center",
            valign="middle"
        )
        label.bind(
            size=lambda w, s: setattr(
                w, "text_size", (max(s[0] - 20, 1), s[1])
            )
        )

        Popup(
            title=title,
            title_font=FONT,
            content=label,
            size_hint=(0.85, 0.55)
        ).open()

    def notify(self, title, message, status=None):
        def update(dt):
            if status:
                self.status_label.text = status
            self.show_message(title, message)

        Clock.schedule_once(update, 0)

    def build(self):
        self.title = "Учёт доходов и расходов"

        self.store = JsonStore(
            str(BASE_DIR / "expenses.json")
        )

        self.expenses = []
        self.incomes = []
        self.id_token = None
        self.user_id = None

        if self.store.exists("expenses"):
            self.expenses = self.store.get(
                "expenses"
            ).get("items", [])

        if self.store.exists("incomes"):
            self.incomes = self.store.get(
                "incomes"
            ).get("items", [])

        self.firebase_config = {}
        config_path = BASE_DIR / "firebase_config.json"

        if config_path.exists():
            try:
                with open(
                    config_path, "r", encoding="utf-8"
                ) as file:
                    self.firebase_config = json.load(file)
            except (OSError, ValueError):
                pass

        layout = BoxLayout(
            orientation="vertical",
            padding=12,
            spacing=7,
            size_hint_y=None
        )

        layout.bind(
            minimum_height=layout.setter("height")
        )

        layout.add_widget(self.make_label(
            "Учёт доходов и расходов",
            font_size=25,
            size_hint_y=None,
            height=55
        ))

        self.amount_input = TextInput(
            hint_text="Введите сумму",
            font_name=FONT,
            multiline=False,
            input_filter="float",
            size_hint_y=None,
            height=44
        )
        layout.add_widget(self.amount_input)

        self.type_spinner = Spinner(
            text="Расход",
            values=("Расход", "Доход"),
            font_name=FONT,
            size_hint_y=None,
            height=44
        )
        layout.add_widget(self.type_spinner)

        self.category_spinner = Spinner(
            text="Выберите категорию",
            values=tuple(
                translate_category(c)
                for c in EXPENSE_CATEGORIES
            ),
            font_name=FONT,
            size_hint_y=None,
            height=44
        )
        layout.add_widget(self.category_spinner)

        self.description_input = TextInput(
            hint_text="Описание операции",
            font_name=FONT,
            multiline=False,
            size_hint_y=None,
            height=44
        )
        layout.add_widget(self.description_input)

        self.operation_button = self.make_button(
            "Добавить расход",
            self.add_operation
        )
        layout.add_widget(self.operation_button)

        self.type_spinner.bind(
            text=self.update_categories
        )

        layout.add_widget(self.make_button(
            "История операций",
            self.show_history
        ))

        layout.add_widget(self.make_button(
            "Аналитика",
            self.show_analytics
        ))

        layout.add_widget(self.make_button(
            "Диаграмма расходов",
            self.show_chart
        ))

        layout.add_widget(self.make_button(
            "Войти в Firebase",
            self.show_login
        ))

        layout.add_widget(self.make_button(
            "Сохранить в облако",
            self.sync_to_cloud
        ))

        layout.add_widget(self.make_button(
            "Загрузить из облака",
            self.confirm_cloud_load
        ))

        self.income_label = self.make_label(
            "Общий доход: 0.00",
            size_hint_y=None,
            height=32
        )
        layout.add_widget(self.income_label)

        self.expense_label = self.make_label(
            "Общие расходы: 0.00",
            size_hint_y=None,
            height=32
        )
        layout.add_widget(self.expense_label)

        self.balance_label = self.make_label(
            "Баланс: 0.00",
            font_size=21,
            bold=True,
            size_hint_y=None,
            height=40
        )
        layout.add_widget(self.balance_label)

        self.status_label = self.make_label(
            "Firebase: Не подключено",
            size_hint_y=None,
            height=32
        )
        layout.add_widget(self.status_label)

        scroll = ScrollView()
        scroll.add_widget(layout)

        self.update_display()
        return scroll

    def update_categories(self, spinner, operation_type):
        if operation_type == "Доход":
            categories = INCOME_CATEGORIES
            self.operation_button.text = "Добавить доход"
        else:
            categories = EXPENSE_CATEGORIES
            self.operation_button.text = "Добавить расход"

        self.category_spinner.values = tuple(
            translate_category(c) for c in categories
        )
        self.category_spinner.text = "Выберите категорию"

    def save_local(self):
        self.store.put(
            "expenses",
            items=self.expenses
        )
        self.store.put(
            "incomes",
            items=self.incomes
        )

    def add_operation(self, instance):
        amount_text = self.amount_input.text.strip()
        selected_category = self.category_spinner.text

        if (
            not amount_text
            or selected_category == "Выберите категорию"
        ):
            self.show_message(
                "Ошибка",
                "Введите сумму и выберите категорию"
            )
            return

        try:
            amount = float(amount_text)
        except ValueError:
            self.show_message(
                "Ошибка",
                "Некорректная сумма"
            )
            return

        if not math.isfinite(amount) or amount <= 0:
            self.show_message(
                "Ошибка",
                "Сумма должна быть больше нуля"
            )
            return

        # Сохраняем категории в прежнем формате
        reverse_categories = {
            value: key
            for key, value in CATEGORY_NAMES.items()
        }

        category = reverse_categories.get(
            selected_category,
            selected_category
        )

        operation = {
            "amount": amount,
            "category": category,
            "description": self.description_input.text.strip(),
            "date": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        }

        if self.type_spinner.text == "Доход":
            self.incomes.append(operation)
            message = "Доход успешно добавлен!"
        else:
            self.expenses.append(operation)
            message = "Расход успешно добавлен!"

        self.save_local()
        self.update_display()

        self.amount_input.text = ""
        self.description_input.text = ""
        self.category_spinner.text = "Выберите категорию"

        self.show_message("Успешно", message)

    def update_display(self):
        income = sum(
            x["amount"] for x in self.incomes
        )
        expense = sum(
            x["amount"] for x in self.expenses
        )

        self.income_label.text = (
            f"Общий доход: {income:.2f}"
        )
        self.expense_label.text = (
            f"Общие расходы: {expense:.2f}"
        )
        self.balance_label.text = (
            f"Баланс: {income - expense:.2f}"
        )

    def show_history(self, instance):
        operations = [
            {**x, "type": "Расход"}
            for x in self.expenses
        ] + [
            {**x, "type": "Доход"}
            for x in self.incomes
        ]

        operations.sort(
            key=lambda x: x.get("date", ""),
            reverse=True
        )

        if operations:
            history_text = "\n\n".join(
                f'Тип: {x["type"]}\n'
                f'Дата: {x["date"]}\n'
                f'Категория: '
                f'{translate_category(x["category"])}\n'
                f'Сумма: {x["amount"]:.2f}\n'
                f'Описание: {x.get("description", "")}'
                for x in operations
            )
        else:
            history_text = "Операций пока нет"

        label = self.make_label(
            history_text,
            size_hint_y=None,
            halign="left",
            valign="top"
        )

        label.bind(
            width=lambda w, v: setattr(
                w, "text_size", (max(v - 20, 1), None)
            ),
            texture_size=lambda w, v: setattr(
                w, "height", max(v[1] + 30, 100)
            )
        )

        scroll = ScrollView()
        scroll.add_widget(label)

        Popup(
            title="История операций",
            title_font=FONT,
            content=scroll,
            size_hint=(0.9, 0.85)
        ).open()

    def show_analytics(self, instance):
        income = sum(
            x["amount"] for x in self.incomes
        )
        expense = sum(
            x["amount"] for x in self.expenses
        )

        text = (
            f"Общий доход: {income:.2f}\n"
            f"Общие расходы: {expense:.2f}\n"
            f"Баланс: {income - expense:.2f}\n\n"
        )

        for title, operations in [
            ("Расходы", self.expenses),
            ("Доходы", self.incomes)
        ]:
            totals = defaultdict(float)

            for item in operations:
                totals[item["category"]] += item["amount"]

            text += f"{title} по категориям:\n"

            if totals:
                for category, amount in totals.items():
                    text += (
                        f"{translate_category(category)}: "
                        f"{amount:.2f}\n"
                    )
            else:
                text += "Операций пока нет\n"

            text += "\n"

        self.show_message("Аналитика", text)

    def show_chart(self, instance):
        totals = defaultdict(float)

        for item in self.expenses:
            totals[item["category"]] += item["amount"]

        if not totals:
            self.show_message(
                "Диаграмма",
                "Сначала добавьте расходы"
            )
            return

        fig, ax = plt.subplots(figsize=(7, 5))

        ax.pie(
            list(totals.values()),
            labels=[
                translate_category(c)
                for c in totals.keys()
            ],
            autopct="%1.1f%%",
            startangle=90
        )

        ax.set_title("Расходы по категориям")
        ax.axis("equal")

        # Русский шрифт для Matplotlib
        if FONT_PATH.exists():
            from matplotlib import font_manager

            font_manager.fontManager.addfont(
                str(FONT_PATH)
            )

            font_properties = (
                font_manager.FontProperties(
                    fname=str(FONT_PATH)
                )
            )

            for text_item in ax.texts:
                text_item.set_fontproperties(
                    font_properties
                )

            ax.title.set_fontproperties(
                font_properties
            )

        fig.tight_layout()

        path = BASE_DIR / "expense_chart.png"
        fig.savefig(str(path), dpi=150)
        plt.close(fig)

        chart_image = Image(
            source=str(path),
            fit_mode="contain"
        )
        chart_image.reload()

        Popup(
            title="Диаграмма расходов",
            title_font=FONT,
            content=chart_image,
            size_hint=(0.9, 0.85)
        ).open()

    def show_login(self, instance):
        content = BoxLayout(
            orientation="vertical",
            padding=12,
            spacing=10
        )

        email_input = TextInput(
            hint_text="Электронная почта",
            font_name=FONT,
            multiline=False,
            size_hint_y=None,
            height=45
        )

        password_input = TextInput(
            hint_text="Пароль",
            font_name=FONT,
            password=True,
            multiline=False,
            size_hint_y=None,
            height=45
        )

        login_button = self.make_button(
            "Войти"
        )

        content.add_widget(email_input)
        content.add_widget(password_input)
        content.add_widget(login_button)

        popup = Popup(
            title="Вход в Firebase",
            title_font=FONT,
            content=content,
            size_hint=(0.85, 0.45)
        )

        def login_clicked(button):
            email = email_input.text.strip()
            password = password_input.text
            password_input.text = ""

            if not email or not password:
                self.show_message(
                    "Ошибка",
                    "Введите почту и пароль"
                )
                return

            popup.dismiss()
            self.status_label.text = "Firebase: Подключение..."

            threading.Thread(
                target=self.firebase_login,
                args=(email, password),
                daemon=True
            ).start()

        login_button.bind(on_press=login_clicked)
        popup.open()

    def firebase_login(self, email, password):
        api_key = self.firebase_config.get("api_key")

        if not api_key:
            self.notify(
                "Ошибка",
                "Не найден ключ Firebase",
                "Firebase: Ошибка подключения"
            )
            return

        url = (
            "https://identitytoolkit.googleapis.com/v1/"
            f"accounts:signInWithPassword?key={api_key}"
        )

        try:
            response = requests.post(
                url,
                json={
                    "email": email,
                    "password": password,
                    "returnSecureToken": True
                },
                timeout=15
            )

            response.raise_for_status()
            data = response.json()

            self.id_token = data["idToken"]
            self.user_id = data["localId"]

            self.notify(
                "Успешно",
                "Вход в Firebase выполнен!",
                "Firebase: Подключено"
            )

        except (requests.RequestException, ValueError, KeyError):
            self.notify(
                "Ошибка",
                "Не удалось войти в Firebase",
                "Firebase: Ошибка подключения"
            )

    def get_cloud_url(self):
        database_url = self.firebase_config.get(
            "database_url", ""
        ).rstrip("/")

        if not database_url.startswith("https://"):
            raise ValueError("Неверный адрес Firebase")

        return (
            f"{database_url}/users/{self.user_id}/"
            "transactions.json"
        )

    def sync_to_cloud(self, instance):
        if not self.id_token:
            self.show_message(
                "Ошибка",
                "Сначала войдите в Firebase"
            )
            return

        data = {
            "expenses": list(self.expenses),
            "incomes": list(self.incomes)
        }

        self.status_label.text = "Firebase: Отправка данных..."

        threading.Thread(
            target=self.upload_data,
            args=(data,),
            daemon=True
        ).start()

    def upload_data(self, data):
        try:
            response = requests.put(
                self.get_cloud_url(),
                params={"auth": self.id_token},
                json=data,
                timeout=20
            )
            response.raise_for_status()

            self.notify(
                "Успешно",
                "Данные сохранены в Firebase!",
                "Firebase: Данные синхронизированы"
            )

        except (requests.RequestException, ValueError):
            self.notify(
                "Ошибка",
                "Не удалось отправить данные",
                "Firebase: Ошибка синхронизации"
            )

    def confirm_cloud_load(self, instance):
        if not self.id_token:
            self.show_message(
                "Ошибка",
                "Сначала войдите в Firebase"
            )
            return

        content = BoxLayout(
            orientation="vertical",
            padding=10,
            spacing=10
        )

        content.add_widget(self.make_label(
            "Облачные данные заменят локальные.\n"
            "Продолжить?"
        ))

        buttons = BoxLayout(
            size_hint_y=None,
            height=45,
            spacing=10
        )

        cancel = self.make_button("Отмена")
        confirm = self.make_button("Загрузить")

        buttons.add_widget(cancel)
        buttons.add_widget(confirm)
        content.add_widget(buttons)

        popup = Popup(
            title="Подтверждение загрузки",
            title_font=FONT,
            content=content,
            size_hint=(0.85, 0.4)
        )

        cancel.bind(
            on_press=lambda x: popup.dismiss()
        )

        def start_load(button):
            popup.dismiss()

            self.status_label.text = (
                "Firebase: Загрузка данных..."
            )

            threading.Thread(
                target=self.download_data,
                daemon=True
            ).start()

        confirm.bind(on_press=start_load)
        popup.open()

    def download_data(self):
        try:
            response = requests.get(
                self.get_cloud_url(),
                params={"auth": self.id_token},
                timeout=20
            )
            response.raise_for_status()

            data = response.json()

            if not isinstance(data, dict):
                self.notify(
                    "Облако",
                    "В облаке пока нет данных",
                    "Firebase: Подключено"
                )
                return

            expenses = data.get("expenses", [])
            incomes = data.get("incomes", [])

            if (
                not isinstance(expenses, list)
                or not isinstance(incomes, list)
            ):
                self.notify(
                    "Ошибка",
                    "Неверный формат облачных данных",
                    "Firebase: Ошибка загрузки"
                )
                return

            Clock.schedule_once(
                lambda dt: self.apply_cloud_data(
                    expenses, incomes
                ),
                0
            )

        except (requests.RequestException, ValueError):
            self.notify(
                "Ошибка",
                "Не удалось загрузить данные",
                "Firebase: Ошибка загрузки"
            )

    def apply_cloud_data(self, expenses, incomes):
        self.expenses = expenses
        self.incomes = incomes

        self.save_local()
        self.update_display()

        self.status_label.text = (
            "Firebase: Данные загружены"
        )

        self.show_message(
            "Успешно",
            "Данные загружены из Firebase!"
        )


if __name__ == "__main__":
    ExpenseTrackerApp().run()