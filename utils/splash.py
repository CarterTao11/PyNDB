# -*- coding: utf-8 -*-
"""
PyNDB 启动画面模块
打包成 exe 时显示的加载动画
"""
import sys
import time
import threading
import tkinter as tk
from tkinter import ttk


class SplashScreen:
    """启动画面类"""
    
    def __init__(self, title="PyNDB", width=400, height=250):
        self.width = width
        self.height = height
        self.title = title
        self.root = None
        self.canvas = None
        self.animation_id = None
        self.dots = 0
        self.status_text = None
        
    def _create_window(self):
        """创建启动窗口"""
        self.root = tk.Tk()
        self.root.title(self.title)
        self.root.geometry(f"{self.width}x{self.height}")
        self.root.resizable(False, False)
        
        # 居中显示
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - self.width) // 2
        y = (screen_height - self.height) // 2
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")
        
        # 设置透明渐变背景效果（使用纯色+圆角模拟）
        self.root.configure(bg='#1e1e1e')
        
        # 去除窗口边框（可选）
        # self.root.overrideredirect(True)
        
        # 创建画布
        self.canvas = tk.Canvas(
            self.root, 
            width=self.width, 
            height=self.height,
            bg='#1e1e1e',
            highlightthickness=0
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
    def _draw_logo(self):
        """绘制Logo区域"""
        # 标题
        self.canvas.create_text(
            self.width // 2, 60,
            text="PyNDB",
            font=("Microsoft YaHei UI", 32, "bold"),
            fill="#4FC3F7"
        )
        
        # 副标题
        self.canvas.create_text(
            self.width // 2, 100,
            text="Database Management Tool",
            font=("Microsoft YaHei UI", 11),
            fill="#888888"
        )
        
    def _draw_loading_animation(self):
        """绘制加载动画"""
        # 加载条背景
        bar_width = 200
        bar_height = 4
        bar_x = (self.width - bar_width) // 2
        bar_y = 160
        
        # 背景条
        self.canvas.create_rectangle(
            bar_x, bar_y,
            bar_x + bar_width, bar_y + bar_height,
            fill="#333333",
            outline=""
        )
        
        # 动态加载条
        self._update_loading_bar(bar_x, bar_y, bar_width, bar_height)
        
    def _update_loading_bar(self, x, y, width, height):
        """更新加载条动画"""
        if self.root is None:
            return
            
        # 简单的左右摆动动画
        import math
        progress = (time.time() % 2) / 2  # 0-1 循环
        
        # 填充宽度
        fill_width = int(width * progress)
        
        # 删除旧的填充条（如果有）
        if hasattr(self, '_loading_bar'):
            self.canvas.delete(self._loading_bar)
        
        # 绘制新的填充条
        self._loading_bar = self.canvas.create_rectangle(
            x, y,
            x + fill_width, y + height,
            fill="#4FC3F7",
            outline=""
        )
        
        # 继续动画
        self.animation_id = self.root.after(50, lambda: self._update_loading_bar(x, y, width, height))
        
    def _draw_status(self):
        """绘制状态文字"""
        self.status_text = self.canvas.create_text(
            self.width // 2, 200,
            text="正在启动服务...",
            font=("Microsoft YaHei UI", 10),
            fill="#666666"
        )
        
    def update_status(self, text):
        """更新状态文字"""
        if self.root and self.status_text:
            self.canvas.itemconfig(self.status_text, text=text)
            self.root.update()
        
    def _animate_dots(self):
        """动画省略号"""
        if self.root is None:
            return
            
        self.dots = (self.dots + 1) % 4
        dots_str = "." * self.dots
        
        # 获取当前状态文字并添加省略号
        current_text = self.canvas.itemcget(self.status_text, "text")
        if "..." in current_text:
            base_text = current_text.split(".")[0]
        else:
            base_text = current_text
            
        self.canvas.itemconfig(self.status_text, text=base_text + dots_str)
        
        # 继续动画
        self.root.after(500, self._animate_dots)
        
    def show(self):
        """显示启动画面"""
        self._create_window()
        self._draw_logo()
        self._draw_loading_animation()
        self._draw_status()
        self._animate_dots()
        
        # 让窗口在最前
        self.root.lift()
        self.root.attributes('-topmost', True)
        self.root.update()
        
        return self.root
    
    def close(self):
        """关闭启动画面"""
        if self.animation_id:
            self.root.after_cancel(self.animation_id)
            
        if self.root:
            # 淡出效果
            try:
                for i in range(10, 0, -1):
                    alpha = i / 10.0
                    self.root.attributes('-alpha', alpha)
                    self.root.update()
                    time.sleep(0.02)
            except:
                pass
                
            self.root.destroy()
            self.root = None


def show_splash(duration=3):
    """
    显示启动画面
    
    Args:
        duration: 显示时长（秒）
    """
    splash = SplashScreen()
    root = splash.show()
    
    # 模拟启动过程
    splash.update_status("正在加载配置")
    root.update()
    time.sleep(0.8)
    
    splash.update_status("正在初始化数据库")
    root.update()
    time.sleep(0.8)
    
    splash.update_status("正在启动服务")
    root.update()
    time.sleep(0.8)
    
    splash.update_status("启动完成")
    root.update()
    time.sleep(0.5)
    
    splash.close()
    return root


if __name__ == "__main__":
    # 测试启动画面
    show_splash()
