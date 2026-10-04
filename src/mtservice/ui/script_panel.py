from __future__ import annotations

import copy
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..devices import PROFILES, Profile
from ..scripts import (
    CommandStep,
    PauseStep,
    RepeatStep,
    Runner,
    RunStats,
    Script,
    Step,
    WaitStep,
    check,
    describe,
    from_json,
    to_json,
)
from .session import Session
from .step_dialog import StepDialog

ROLE = Qt.ItemDataRole.UserRole


class RunnerBridge(QObject):
    started = Signal(object)
    failed = Signal(object, str)
    stats = Signal(object)
    finished = Signal(str)

    def step_started(self, path):
        self.started.emit(path)

    def step_failed(self, path, message):
        self.failed.emit(path, message)

    def stats_changed(self, stats):
        self.stats.emit(copy.copy(stats))


def _human(path: tuple[int, ...]) -> str:
    return ".".join(str(i + 1) for i in path)


class ScriptPanel(QGroupBox):
    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__("Сценарий", parent)
        self.session = session
        self._profile_key = session.profile.key
        self._path: Path | None = None
        self._runner: Runner | None = None
        self._current: QTreeWidgetItem | None = None
        self._stats = RunStats()
        self._finished_after = 0

        self._bridge = RunnerBridge()
        self._bridge.started.connect(self._highlight)
        self._bridge.failed.connect(self._on_failed)
        self._bridge.stats.connect(self._on_stats)
        self._bridge.finished.connect(self._on_finished)

        self._file_label = QLabel()
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.itemDoubleClicked.connect(lambda *_: self._edit())

        self._stop_on_error = QCheckBox("Остановиться при ошибке")
        self._stop_on_error.setChecked(True)
        self._stats_label = QLabel()
        self._timer = QTimer(self, interval=500)
        self._timer.timeout.connect(self._show_stats)

        def button(text: str, handler) -> QPushButton:
            widget = QPushButton(text)
            widget.clicked.connect(handler)
            return widget

        self._run_button = button("Запустить", self._run)
        self._stop_button = button("Стоп", self.stop)
        self._stop_button.setEnabled(False)
        self._editing = [
            button("Новый", self._new),
            button("Открыть…", self._open),
            button("Сохранить…", self._save),
            button("+ Команда", lambda: self._add(CommandStep(self._profile().commands[0].key))),
            button("+ Пауза", lambda: self._add(PauseStep())),
            button("+ Повтор", lambda: self._add(RepeatStep(times=10))),
            button("+ Ожидание", lambda: self._add(WaitStep(bit=self._profile().sensors[0].bit))),
            button("Изменить", self._edit),
            button("Удалить", self._remove),
            button("Выше", lambda: self._shift(-1)),
            button("Ниже", lambda: self._shift(1)),
            self._stop_on_error,
        ]

        files = QHBoxLayout()
        for widget in self._editing[:3]:
            files.addWidget(widget)
        files.addWidget(self._file_label, 1)
        add = QHBoxLayout()
        for widget in self._editing[3:7]:
            add.addWidget(widget)
        edit = QHBoxLayout()
        for widget in self._editing[7:11]:
            edit.addWidget(widget)
        run = QHBoxLayout()
        run.addWidget(self._run_button)
        run.addWidget(self._stop_button)
        run.addWidget(self._stats_label, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(files)
        layout.addWidget(self._tree, 1)
        layout.addLayout(add)
        layout.addLayout(edit)
        layout.addWidget(self._stop_on_error)
        layout.addLayout(run)

        session.profile_changed.connect(self._on_profile)
        session.connection_changed.connect(self._on_connection)
        self._update_title()
        self._show_stats()

    def script(self) -> Script:
        return Script(self._profile_key, self._collect(self._tree.invisibleRootItem()),
                      self._stop_on_error.isChecked())

    def load(self, script: Script) -> None:
        self._profile_key = script.profile
        self._stop_on_error.setChecked(script.stop_on_error)
        self._tree.clear()
        self._fill(self._tree.invisibleRootItem(), script.steps)
        self._tree.expandAll()
        self._update_title()

    def _profile(self) -> Profile:
        return PROFILES[self._profile_key]

    def _collect(self, parent: QTreeWidgetItem) -> list[Step]:
        steps = []
        for index in range(parent.childCount()):
            item = parent.child(index)
            step = copy.deepcopy(item.data(0, ROLE))
            if isinstance(step, RepeatStep):
                step.steps = self._collect(item)
            steps.append(step)
        return steps

    def _fill(self, parent: QTreeWidgetItem, steps: list[Step]) -> None:
        for step in steps:
            item = self._make_item(step)
            parent.addChild(item)
            if isinstance(step, RepeatStep):
                self._fill(item, step.steps)

    def _make_item(self, step: Step) -> QTreeWidgetItem:
        item = QTreeWidgetItem()
        self._set_step(item, step)
        return item

    def _set_step(self, item: QTreeWidgetItem, step: Step) -> None:
        if isinstance(step, RepeatStep):
            step = RepeatStep(step.times)
        item.setData(0, ROLE, step)
        item.setText(0, describe(step, self._profile()))

    def _update_title(self) -> None:
        name = self._path.name if self._path else "без имени"
        self._file_label.setText(f"{name} · {self._profile().model}")

    def _on_profile(self, profile: Profile) -> None:
        if self._tree.topLevelItemCount() == 0:
            self._profile_key = profile.key
            self._update_title()

    def _on_connection(self, connected: bool) -> None:
        if not connected and self._runner:
            self._runner.stop()

    def _new(self) -> None:
        self._tree.clear()
        self._path = None
        self._profile_key = self.session.profile.key
        self._update_title()

    def _open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Открыть сценарий", "", "Сценарий (*.json)")
        if not path:
            return
        try:
            script = from_json(Path(path).read_text(encoding="utf-8"))
            if script.profile not in PROFILES:
                raise ValueError(f"неизвестная модель {script.profile}")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Сценарий", f"Не удалось открыть файл:\n{exc}")
            return
        self._path = Path(path)
        self.load(script)

    def _save(self) -> None:
        start = str(self._path) if self._path else "сценарий.json"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить сценарий", start, "Сценарий (*.json)")
        if not path:
            return
        self._path = Path(path)
        self._path.write_text(to_json(self.script()), encoding="utf-8")
        self._update_title()

    def _add(self, step: Step) -> None:
        dialog = StepDialog(step, self._profile(), self)
        if not dialog.exec():
            return
        item = self._make_item(dialog.result_step())
        selected = self._tree.currentItem()
        if selected is None:
            self._tree.addTopLevelItem(item)
        elif isinstance(selected.data(0, ROLE), RepeatStep):
            selected.addChild(item)
            selected.setExpanded(True)
        else:
            parent = selected.parent() or self._tree.invisibleRootItem()
            parent.insertChild(parent.indexOfChild(selected) + 1, item)
        self._tree.setCurrentItem(item)

    def _edit(self) -> None:
        item = self._tree.currentItem()
        if item is None or self._runner:
            return
        dialog = StepDialog(item.data(0, ROLE), self._profile(), self)
        if dialog.exec():
            self._set_step(item, dialog.result_step())

    def _remove(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return
        parent = item.parent() or self._tree.invisibleRootItem()
        parent.removeChild(item)

    def _shift(self, delta: int) -> None:
        item = self._tree.currentItem()
        if item is None:
            return
        parent = item.parent() or self._tree.invisibleRootItem()
        index = parent.indexOfChild(item)
        target = index + delta
        if not 0 <= target < parent.childCount():
            return
        expanded = item.isExpanded()
        parent.takeChild(index)
        parent.insertChild(target, item)
        item.setExpanded(expanded)
        self._tree.setCurrentItem(item)

    def _run(self) -> None:
        if not self.session.connected:
            self.session.message.emit("Сценарий: сначала подключитесь к устройству")
            return
        script = self.script()
        profile = self.session.profile
        if script.profile != profile.key:
            QMessageBox.warning(
                self, "Сценарий",
                f"Сценарий составлен для {self._profile().model}, а подключён {profile.model}.",
            )
            return
        problems = check(script, profile)
        if problems:
            QMessageBox.warning(self, "Сценарий", "\n".join(problems))
            return
        if not script.steps:
            return
        self._runner = Runner(script, profile, self.session.call, self._bridge)
        self._stats = RunStats()
        self._set_running(True)
        self.session.message.emit("Сценарий запущен")
        threading.Thread(target=self._worker, args=(self._runner,), daemon=True).start()

    def _worker(self, runner: Runner) -> None:
        try:
            outcome = runner.run()
        except Exception as exc:
            self._bridge.failed.emit((), str(exc))
            outcome = "failed"
        self._bridge.finished.emit(outcome)

    def stop(self) -> None:
        if self._runner:
            self._runner.stop()

    def _set_running(self, running: bool) -> None:
        for widget in self._editing:
            widget.setEnabled(not running)
        self._run_button.setEnabled(not running)
        self._stop_button.setEnabled(running)
        if running:
            self._timer.start()
        else:
            self._timer.stop()

    def _item_at(self, path: tuple[int, ...]) -> QTreeWidgetItem | None:
        item = self._tree.invisibleRootItem()
        for index in path:
            if index >= item.childCount():
                return None
            item = item.child(index)
        return item

    def _highlight(self, path: tuple[int, ...]) -> None:
        if self._current is not None:
            self._current.setFont(0, QFont())
        self._current = self._item_at(path) if path else None
        if self._current is not None:
            font = QFont()
            font.setBold(True)
            self._current.setFont(0, font)
            self._tree.scrollToItem(self._current)

    def _on_failed(self, path: tuple[int, ...], message: str) -> None:
        where = f"шаг {_human(path)}" if path else "проверка"
        self.session.message.emit(f"Сценарий, {where}: {message}")

    def _on_stats(self, stats: RunStats) -> None:
        self._stats = stats
        self._show_stats()

    def _show_stats(self) -> None:
        stats = self._stats
        elapsed = int(stats.elapsed) if self._runner else self._finished_after
        minutes, seconds = divmod(elapsed, 60)
        self._stats_label.setText(
            f"команд {stats.commands} · ошибок {stats.failures} · "
            f"циклов {stats.iterations} · {minutes:02d}:{seconds:02d}"
        )

    def _on_finished(self, outcome: str) -> None:
        text = {"done": "выполнен", "stopped": "остановлен", "failed": "прерван из-за ошибки"}[outcome]
        self._finished_after = int(self._stats.elapsed)
        self._runner = None
        self._show_stats()
        self._set_running(False)
        self._highlight(())
        self.session.message.emit(
            f"Сценарий {text}: команд {self._stats.commands}, ошибок {self._stats.failures}, "
            f"циклов {self._stats.iterations}"
        )
