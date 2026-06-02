import sys
import math
import random
from PySide6 import QtCore, QtGui, QtWidgets

class SiriWaveformWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(260, 76)

        # State & variables
        self.state = "listen"  # listen, transcribe, review
        self.theme = "dark"    # dark, light
        self.bg_opacity = 0.65 # Perfekt balanserad Fluent Slate-Gray opacitet (65%)
        self.message = "Lyssnar..."
        self.phase = 0.0
        self.level = 0.5
        self.smoothed_level = 0.5

        # UI Setup
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)  # ~60 FPS

        # Dynamically size window to fit initial text
        self._resize_to_message()

        # Move to screen center for easy viewing
        self._center_on_screen()

    def _center_on_screen(self):
        screen = QtWidgets.QApplication.primaryScreen()
        if screen:
            rect = screen.availableGeometry()
            self.move(rect.center().x() - self.width() // 2, rect.center().y() - self.height() // 2 - 100)

    def _resize_to_message(self):
        """Dynamiskt beräknar fönstrets bredd baserat på textens faktiska längd."""
        font = QtGui.QFont("Segoe UI", 11, QtGui.QFont.Weight.Bold)
        metrics = QtGui.QFontMetrics(font)
        text_width = metrics.horizontalAdvance(self.message)

        # Lägg till luft (padding) på sidorna av texten (eftersom bakgrunden är vågen)
        width = text_width + 64
        # Sätt gränser för minsta/maxbredd
        width = max(160, min(width, 420))

        if width != self.width():
            old_center = self.geometry().center()
            self.setFixedSize(width, 76)
            # Centrera fönstret runt dess tidigare mittpunkt så storleksändringen blir fluid
            self.move(old_center.x() - width // 2, old_center.y() - 38)

    def _tick(self):
        self.phase += 0.05

        # Simulate sound level in listening state
        if self.state == "listen":
            target = 0.15 + abs(math.sin(self.phase * 0.7)) * 0.5 + random.uniform(-0.05, 0.05)
            self.smoothed_level = self.smoothed_level * 0.8 + max(0.05, min(1.0, target)) * 0.2
        else:
            self.smoothed_level = self.smoothed_level * 0.9

        self.update()

    def set_state(self, state: str, custom_text: str | None = None):
        self.state = state
        if custom_text is not None:
            self.message = custom_text
        else:
            if state == "listen":
                self.message = "Lyssnar..."
            elif state == "transcribe":
                self.message = "Transkriberar via Staik..."
            elif state == "review":
                self.message = "Polerar text..."
        self._resize_to_message()
        self.update()

    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self.update()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            # Cycle state
            states = ["listen", "transcribe", "review"]
            next_idx = (states.index(self.state) + 1) % len(states)
            self.set_state(states[next_idx])
        elif event.button() == QtCore.Qt.MouseButton.RightButton:
            # Toggle theme
            self.toggle_theme()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        w = float(self.width())
        pad = 12.0
        pill_w = w - pad * 2.0
        pill_h = 52.0

        rect = QtCore.QRectF(pad, pad, pill_w, pill_h)
        rx = 16.0  # Ökad hörnradie för mycket mjukare, modernare form

        # 1. Multi-layered Ambient Shadow för en extremt mjuk skugga (suddar ut boxens kanter)
        if self.bg_opacity > 0.0:
            for offset, alpha in [(1, 14), (2, 18), (4, 12), (7, 6)]:
                s_rect = rect.translated(0, offset).adjusted(-offset/1.5, -offset/1.5, offset/1.5, offset/1.5)
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(QtGui.QColor(0, 0, 0, alpha))
                painter.drawRoundedRect(s_rect, rx + offset/1.5, rx + offset/1.5)

        # 2. Base Background (Acrylic Glass-effekt med Windows 11 Slate Gray / Charcoal-färg)
        bg_grad = QtGui.QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top())
        border_grad = QtGui.QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top())

        # Räkna ut alfakomponenter baserat på vår opacitets-slider (0.0 till 1.0)
        center_alpha = int(self.bg_opacity * 255)
        # Kantopacitet fadar till 0 endast om vi har transparens (< 100%) för att ge organiskt svävande känsla
        edge_alpha = 0 if self.bg_opacity < 1.0 else center_alpha

        # Vi använder en modern Slate Gray (skiffergrå / grafitgrå) färg istället för hård kolsvart.
        # Skiffergrå ger mycket bättre ljusbrytning, kontrast och mjukhet på skrivbordet!
        if self.theme == "dark":
            base_r, base_g, base_b = 32, 35, 43  # Premium Slate Charcoal
            border_r, border_g, border_b = 255, 255, 255
            border_alpha = int(self.bg_opacity * 34) # Mjuk ljus innerlinje för Windows-kontrast
        else:
            base_r, base_g, base_b = 236, 235, 230  # Soft Warm Light Gray
            border_r, border_g, border_b = 0, 0, 0
            border_alpha = int(self.bg_opacity * 20)

        bg_grad.setColorAt(0.0, QtGui.QColor(base_r, base_g, base_b, edge_alpha))
        bg_grad.setColorAt(0.15, QtGui.QColor(base_r, base_g, base_b, center_alpha))
        bg_grad.setColorAt(0.85, QtGui.QColor(base_r, base_g, base_b, center_alpha))
        bg_grad.setColorAt(1.0, QtGui.QColor(base_r, base_g, base_b, edge_alpha))

        border_grad.setColorAt(0.0, QtGui.QColor(border_r, border_g, border_b, 0))
        border_grad.setColorAt(0.15, QtGui.QColor(border_r, border_g, border_b, border_alpha))
        border_grad.setColorAt(0.85, QtGui.QColor(border_r, border_g, border_b, border_alpha))
        border_grad.setColorAt(1.0, QtGui.QColor(border_r, border_g, border_b, 0))

        painter.setPen(QtGui.QPen(border_grad, 1.0))
        painter.setBrush(bg_grad)
        painter.drawRoundedRect(rect, rx, rx)

        # Draw dynamic waves / background visualizations inside the pill container
        painter.save()
        # Clip to rounded rect to keep everything nicely inside the container
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, rx, rx)
        painter.setClipPath(path)

        if self.state == "listen":
            self._draw_siri_waveform(painter, rect)
        elif self.state == "transcribe":
            self._draw_transcribe_helix(painter, rect)
        elif self.state == "review":
            self._draw_review_ribbon(painter, rect)

        painter.restore()

        # 3. Draw Text with Animated Shimmer Effect
        self._draw_shimmering_text(painter, rect)

    def _draw_siri_waveform(self, painter, rect):
        """Draws layered translucent Siri-like waveforms across the entire background."""
        cy = rect.center().y()
        w = rect.width()
        h = rect.height()

        # Wave configurations (frequency, phase offset, amplitude multiplier, color, opacity)
        # We adjust colors depending on Dark/Light theme
        if self.theme == "dark":
            waves = [
                (0.04,  0.0,  0.40, QtGui.QColor(0, 106, 167),   60),   # Swedish Blue
                (0.055, 2.1,  0.32, QtGui.QColor(64, 199, 255),  85),   # Cyan
                (0.03,  4.2,  0.25, QtGui.QColor(254, 204, 2),   75),   # Swedish Gold
                (0.045, 1.3,  0.30, QtGui.QColor(127, 155, 85),  65)    # Mix green
            ]
        else:
            waves = [
                (0.04,  0.0,  0.38, QtGui.QColor(0, 90, 140),    45),
                (0.055, 2.1,  0.30, QtGui.QColor(30, 170, 220),  60),
                (0.03,  4.2,  0.24, QtGui.QColor(220, 170, 2),   50),
                (0.045, 1.3,  0.28, QtGui.QColor(100, 130, 70),  40)
            ]

        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

        # Draw each wave
        for freq, phase_off, amp_mult, color, opacity in waves:
            path = QtGui.QPainterPath()
            path.moveTo(rect.left(), cy)

            # Amplitude is modulated by the smoothed voice input level
            amplitude = h * amp_mult * self.smoothed_level

            steps = 60
            for i in range(steps + 1):
                x = rect.left() + (w * i / steps)
                # Apply a bell curve envelope (sin) to taper the wave at the left and right edges
                envelope = math.sin(math.pi * i / steps)
                # Compute sine wave value
                angle = (i * freq * 10.0) - (self.phase * 2.5) + phase_off
                y = cy + math.sin(angle) * amplitude * envelope
                path.lineTo(x, y)

            pen_color = QtGui.QColor(color)
            pen_color.setAlpha(opacity)
            painter.setPen(QtGui.QPen(pen_color, 2.2))
            painter.drawPath(path)

    def _draw_transcribe_helix(self, painter, rect):
        """Draws a flowing double-helix wave pattern across the background."""
        cy = rect.center().y()
        w = rect.width()

        steps = 80
        color1 = QtGui.QColor(254, 204, 2, 90) if self.theme == "dark" else QtGui.QColor(220, 170, 2, 110) # Gold
        color2 = QtGui.QColor(0, 190, 255, 95) if self.theme == "dark" else QtGui.QColor(0, 110, 200, 115) # Blue/Cyan

        # Helix 1
        path1 = QtGui.QPainterPath()
        # Helix 2
        path2 = QtGui.QPainterPath()

        amp = 11.0
        freq = 0.075

        path1.moveTo(rect.left(), cy)
        path2.moveTo(rect.left(), cy)

        for i in range(steps + 1):
            x = rect.left() + (w * i / steps)
            envelope = math.sin(math.pi * i / steps)

            # Wave 1 (Betydligt långsammare fasförskjutning och bredare våglängd för lugnare känsla)
            angle1 = (i * freq * 2.5) - (self.phase * 1.0)
            y1 = cy + math.sin(angle1) * amp * envelope
            path1.lineTo(x, y1)

            # Wave 2 (180 grader ur fas)
            angle2 = angle1 + math.pi
            y2 = cy + math.sin(angle2) * amp * envelope
            path2.lineTo(x, y2)

        # Rita vågorna
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(QtGui.QPen(color1, 2.2, QtCore.Qt.PenStyle.SolidLine))
        painter.drawPath(path1)

        painter.setPen(QtGui.QPen(color2, 2.2, QtCore.Qt.PenStyle.SolidLine))
        painter.drawPath(path2)

        # Rita vertikala "stegpinnar" för DNA-helix/process-känsla
        rung_pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 25) if self.theme == "dark" else QtGui.QColor(0, 0, 0, 15), 1.0)
        painter.setPen(rung_pen)
        for i in range(2, steps, 4):
            x = rect.left() + (w * i / steps)
            envelope = math.sin(math.pi * i / steps)
            angle = (i * freq * 2.5) - (self.phase * 1.0)
            y1 = cy + math.sin(angle) * amp * envelope
            y2 = cy + math.sin(angle + math.pi) * amp * envelope
            painter.drawLine(QtCore.QPointF(x, y1), QtCore.QPointF(x, y2))

            # Draw tiny joint dots on the wave peaks/valleys
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(color1)
            painter.drawEllipse(QtCore.QPointF(x, y1), 1.8, 1.8)
            painter.setBrush(color2)
            painter.drawEllipse(QtCore.QPointF(x, y2), 1.8, 1.8)
            painter.setPen(rung_pen)

    def _draw_review_ribbon(self, painter, rect):
        """Draws a beautiful, ultra-smooth horizontal single ribbon with a calming teal/cyan aurora flow."""
        cy = rect.center().y()
        w = rect.width()
        h = rect.height()

        # We draw two overlapping, very wide, very slow waves
        steps = 60
        # Low frequency (wide, smooth waves)
        freq = 0.02
        amp = h * 0.18 # Very gentle wave amplitude, subtle

        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

        # Wave 1 (Teal/Emerald gradient)
        path1 = QtGui.QPainterPath()
        path1.moveTo(rect.left(), cy)
        # Wave 2 (Cyan/Indigo gradient, slightly shifted)
        path2 = QtGui.QPainterPath()
        path2.moveTo(rect.left(), cy)

        for i in range(steps + 1):
            x = rect.left() + (w * i / steps)
            envelope = math.sin(math.pi * i / steps) # Tapers at edges

            # Slow, wide wave 1
            angle1 = (i * freq * 10.0) - (self.phase * 0.6)
            y1 = cy + math.sin(angle1) * amp * envelope
            path1.lineTo(x, y1)

            # Slow, wide wave 2 (shifted)
            angle2 = (i * freq * 8.5) - (self.phase * 0.5) + 1.8
            y2 = cy + math.sin(angle2) * (amp * 0.8) * envelope
            path2.lineTo(x, y2)

        # Draw with glowing gradients
        grad1 = QtGui.QLinearGradient(rect.left(), cy, rect.right(), cy)
        if self.theme == "dark":
            grad1.setColorAt(0.0, QtGui.QColor(0, 200, 150, 0))
            grad1.setColorAt(0.5, QtGui.QColor(0, 180, 160, 130)) # Calming Teal
            grad1.setColorAt(1.0, QtGui.QColor(0, 200, 150, 0))
        else:
            grad1.setColorAt(0.0, QtGui.QColor(0, 150, 130, 0))
            grad1.setColorAt(0.5, QtGui.QColor(0, 150, 120, 150))
            grad1.setColorAt(1.0, QtGui.QColor(0, 150, 130, 0))

        painter.setPen(QtGui.QPen(grad1, 2.5))
        painter.drawPath(path1)

        grad2 = QtGui.QLinearGradient(rect.left(), cy, rect.right(), cy)
        if self.theme == "dark":
            grad2.setColorAt(0.0, QtGui.QColor(0, 130, 220, 0))
            grad2.setColorAt(0.5, QtGui.QColor(0, 150, 220, 110)) # Calming Cyan-Blue
            grad2.setColorAt(1.0, QtGui.QColor(0, 130, 220, 0))
        else:
            grad2.setColorAt(0.0, QtGui.QColor(0, 100, 180, 0))
            grad2.setColorAt(0.5, QtGui.QColor(0, 120, 200, 130))
            grad2.setColorAt(1.0, QtGui.QColor(0, 100, 180, 0))

        painter.setPen(QtGui.QPen(grad2, 1.8))
        painter.drawPath(path2)

        # Add ultra-subtle shimmering particles
        for i in range(2):
            p_phase = self.phase * 0.4 + i * math.pi
            px = rect.left() + (rect.width() * 0.25) + ((math.sin(p_phase) + 1.0) / 2.0) * (rect.width() * 0.5)
            py = cy + math.cos(p_phase * 1.8) * 4.0
            painter.setBrush(QtGui.QColor(255, 255, 255, 120) if self.theme == "dark" else QtGui.QColor(0, 150, 130, 140))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawEllipse(QtCore.QPointF(px, py), 1.5, 1.5)

    def _draw_shimmering_text(self, painter, rect):
        """Draws the text centered inside the pill with a beautiful shimmering gradient."""
        # Use bold DemiBold Segoe UI
        font = QtGui.QFont("Segoe UI", 11, QtGui.QFont.Weight.Bold)
        painter.setFont(font)

        # Center the text
        metrics = QtGui.QFontMetrics(font)
        text_w = metrics.horizontalAdvance(self.message)

        tx = rect.left() + (rect.width() - text_w) / 2.0
        ty = rect.top() + (rect.height() + metrics.ascent() - metrics.descent()) / 2.0

        # Create a linear gradient for the text shimmer
        # Sweep x position based on self.phase
        gradient_width = 80.0
        # Loop the sweep from left of text to right of text
        total_sweep_width = text_w + gradient_width * 2
        sweep_pos = tx - gradient_width + (self.phase * 12.0) % total_sweep_width

        gradient = QtGui.QLinearGradient(sweep_pos, ty, sweep_pos + gradient_width, ty)

        if self.theme == "dark":
            text_base_color = QtGui.QColor(230, 235, 245)
            shimmer_highlight = QtGui.QColor(255, 255, 255)
            gradient.setColorAt(0.0, text_base_color)
            gradient.setColorAt(0.3, text_base_color)
            gradient.setColorAt(0.5, shimmer_highlight)
            gradient.setColorAt(0.7, text_base_color)
            gradient.setColorAt(1.0, text_base_color)
        else:
            text_base_color = QtGui.QColor(17, 24, 39)
            shimmer_highlight = QtGui.QColor(0, 106, 167)
            gradient.setColorAt(0.0, text_base_color)
            gradient.setColorAt(0.35, text_base_color)
            gradient.setColorAt(0.5, shimmer_highlight)
            gradient.setColorAt(0.65, text_base_color)
            gradient.setColorAt(1.0, text_base_color)

        painter.setPen(QtGui.QPen(QtGui.QBrush(gradient), 1.0))
        painter.drawText(QtCore.QPointF(tx, ty), self.message)


class ControlPanel(QtWidgets.QWidget):
    """Hjälp-kontrollpanel för att interaktivt styra indikatorns tillstånd och testa textlängder."""
    def __init__(self, indicator_widget):
        super().__init__()
        self.indicator = indicator_widget
        self.setWindowFlags(
            QtCore.Qt.WindowType.Window
            | QtCore.Qt.WindowType.CustomizeWindowHint
            | QtCore.Qt.WindowType.WindowTitleHint
        )
        self.setWindowTitle("FreeWispr Mockup Kontrollpanel")
        self.setFixedSize(320, 390)
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e24;
                color: #ffffff;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton {
                background-color: #2e2e38;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #3e3e48;
                border-color: #006AA7;
            }
            QPushButton:pressed {
                background-color: #006AA7;
            }
            QLineEdit {
                background-color: #2e2e38;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 6px;
                color: #ffffff;
                font-weight: bold;
                font-size: 11px;
            }
            QLineEdit:focus {
                border-color: #006AA7;
            }
            QLabel {
                font-size: 10px;
                color: #888;
            }
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)

        title = QtWidgets.QLabel("VÄLJ TILLSTÅND:")
        title.setStyleSheet("font-weight: bold; color: #aaa; margin-top: 2px;")
        layout.addWidget(title)

        btn_listen = QtWidgets.QPushButton("🎙️ Lyssnar (Röstvåg)")
        btn_listen.clicked.connect(lambda: self._set_state_sync("listen"))
        layout.addWidget(btn_listen)

        btn_transcribe = QtWidgets.QPushButton("🔄 Transkriberar (Helix - breda vågor)")
        btn_transcribe.clicked.connect(lambda: self._set_state_sync("transcribe"))
        layout.addWidget(btn_transcribe)

        btn_review = QtWidgets.QPushButton("✨ Granskar (Teal/Cyan Aurora)")
        btn_review.clicked.connect(lambda: self._set_state_sync("review"))
        layout.addWidget(btn_review)

        layout.addSpacing(4)

        text_title = QtWidgets.QLabel("SKRIV DIN EGEN TEXT (DYNAMISK BREDD):")
        text_title.setStyleSheet("font-weight: bold; color: #aaa;")
        layout.addWidget(text_title)

        self.text_input = QtWidgets.QLineEdit()
        self.text_input.setText(self.indicator.message)
        self.text_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.text_input)

        layout.addSpacing(4)

        btn_theme = QtWidgets.QPushButton("🌗 Växla Ljust / Mörkt läge")
        btn_theme.clicked.connect(self.indicator.toggle_theme)
        layout.addWidget(btn_theme)

        self.slider_label = QtWidgets.QLabel(f"BAKGRUNDSOPACITET: {int(self.indicator.bg_opacity * 100)}%")
        self.slider_label.setStyleSheet("font-weight: bold; color: #aaa; margin-top: 4px;")
        layout.addWidget(self.slider_label)

        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(self.indicator.bg_opacity * 100))
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #444;
                height: 6px;
                background: #2e2e38;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #006AA7;
                border: 1px solid #006AA7;
                width: 14px;
                height: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #40C7FF;
                border-color: #40C7FF;
            }
        """)
        self.slider.valueChanged.connect(self._on_opacity_changed)
        layout.addWidget(self.slider)

        instruction = QtWidgets.QLabel("Instruktion: Du kan skriva vad som helst i textrutan (t.ex. 'Transkriberar via Staik...') så ändrar indikatorn storlek fjädrande kring sin mittpunkt för att matcha!")
        instruction.setWordWrap(True)
        instruction.setStyleSheet("color: #777; font-size: 9px;")
        layout.addWidget(instruction)

        self.move_beside_indicator()

    def _set_state_sync(self, state: str):
        self.indicator.set_state(state)
        # Blockera signaler tillfälligt för att inte trigga on_text_changed vid text-uppdatering
        self.text_input.blockSignals(True)
        self.text_input.setText(self.indicator.message)
        self.text_input.blockSignals(False)

    def _on_text_changed(self, text):
        self.indicator.message = text
        self.indicator._resize_to_message()
        self.indicator.update()

    def _on_opacity_changed(self, value):
        opacity = value / 100.0
        self.indicator.bg_opacity = opacity
        self.slider_label.setText(f"BAKGRUNDSOPACITET: {value}%")
        self.indicator.update()

    def move_beside_indicator(self):
        # Position slightly to the right or below the indicator
        self.move(self.indicator.x() - 30, self.indicator.y() + 80)

    def closeEvent(self, event):
        self.indicator.close()
        event.accept()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)

    # Create the beautiful Siri background indicator mockup
    indicator = SiriWaveformWidget()
    indicator.show()

    # Create the control panel helper
    controls = ControlPanel(indicator)
    controls.show()

    sys.exit(app.exec())
