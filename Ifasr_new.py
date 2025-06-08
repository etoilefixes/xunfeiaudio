# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import json
import os
import time
import requests
import urllib.parse
import logging
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import sys
import traceback
import zipfile
import tempfile
import io
import shutil
import pyperclip



# 讯飞API配置
lfasr_host = 'https://raasr.xfyun.cn/v2/api'
api_upload = '/upload'
api_get_result = '/getResult'

# 错误码映射
ERROR_CODES = {
    0: "成功",
    10005: "参数无效",
    10006: "无效的签名",
    10007: "签名过期",
    10008: "请求太频繁",
    10009: "余额不足",
    10010: "无效的订单ID",
    10011: "无效的音频文件",
    10012: "音频时长超过限制",
    10019: "并发超过限制",
    10029: "订单不存在",
    10101: "内部错误",
    10102: "转写失败",
    10103: "转写超时",
    10163: "输入参数有误",
    10205: "无效的appid",
    10800: "无效的音频格式"
}

class LFASRClient:
    """讯飞语音转写API客户端"""
    
    def __init__(self, appid, secret_key, max_retry=3, poll_interval=5, result_type="transfer,predict"):
        """
        初始化客户端
        
        :param appid: 讯飞应用ID
        :param secret_key: 讯飞应用密钥
        :param max_retry: 最大重试次数
        :param poll_interval: 轮询结果间隔(秒)
        :param result_type: 结果类型 (transfer-最终结果, predict-预测结果)
        """
        self.appid = appid
        self.secret_key = secret_key
        self.max_retry = max_retry
        self.poll_interval = poll_interval
        self.result_type = result_type
        self.update_timestamp()
        logger.info(f"初始化客户端成功 | APPID: {appid}")
    
    def update_timestamp(self):
        """更新时间戳和签名"""
        self.ts = str(int(time.time()))
        self.signa = self._generate_signa()
        
    def _generate_signa(self):
        """生成API签名"""
        data = (self.appid + self.ts).encode('utf-8')
        
        # 计算MD5
        m2 = hashlib.md5()
        m2.update(data)
        md5_value = m2.hexdigest()
        
        # 计算HMAC-SHA1
        signa = hmac.new(
            self.secret_key.encode('utf-8'),
            md5_value.encode('utf-8'),
            hashlib.sha1
        ).digest()
        
        # Base64编码
        return base64.b64encode(signa).decode('utf-8')
    
    def upload_file(self, file_path):
        """
        上传音频文件到讯飞服务器
        
        :param file_path: 本地音频文件路径
        :return: 上传响应结果
        """
        logger.info(f"开始上传文件: {file_path}")
        
        # 验证文件存在性
        if not os.path.exists(file_path):
            logger.error(f"文件不存在: {file_path}")
            raise FileNotFoundError(f"指定文件不存在: {file_path}")
        
        # 获取文件信息
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        
        # 构建请求参数
        params = {
            'appId': self.appid,
            'signa': self.signa,
            'ts': self.ts,
            "fileSize": file_size,
            "fileName": file_name,
            "duration": self._estimate_duration(file_path)
        }
        
        logger.debug(f"上传参数: {params}")
        
        # 构建完整URL
        url = f"{lfasr_host}{api_upload}?{urllib.parse.urlencode(params)}"
        
        try:
            # 读取文件内容
            with open(file_path, 'rb') as f:
                file_data = f.read()
                
            # 发送请求
            response = requests.post(
                url, 
                data=file_data,
                headers={"Content-type": "application/octet-stream"}
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"上传失败: {str(e)}")
            raise
            
        # 检查响应状态
        if response.status_code != 200:
            logger.error(f"上传失败 HTTP {response.status_code}")
            raise Exception(f"上传失败 HTTP {response.status_code}")
        
        try:
            result = response.json()
        except json.JSONDecodeError:
            logger.error("响应解析失败")
            raise
            
        # 检查API错误码
        if result.get('code') != 0:
            error_msg = ERROR_CODES.get(result['code'], "未知错误")
            logger.error(f"上传失败: {error_msg} ({result['code']})")
            raise Exception(f"API错误: {error_msg} (code: {result['code']})")
        
        logger.info(f"上传成功 | OrderID: {result['content']['orderId']}")
        return result
    
    def _estimate_duration(self, file_path):
        """估计音频时长(简化版)"""
        file_size = os.path.getsize(file_path)
        # 简单假设: 16bit/16000Hz/单声道的wav文件 (1秒≈32KB)
        duration = int(file_size / 32000)
        logger.info(f"估算音频时长: {duration}秒 | 文件大小: {file_size}字节")
        return str(duration)
    
    def get_transcription_result(self, upload_result):
        """
        获取语音转写结果
        
        :param upload_result: 上传方法返回的结果
        :return: 转写结果
        """
        self.update_timestamp()  # 更新签名
        order_id = upload_result['content']['orderId']
        logger.info(f"开始获取转写结果 | OrderID: {order_id}")
        
        # 构建请求参数
        params = {
            'appId': self.appid,
            'signa': self.signa,
            'ts': self.ts,
            'orderId': order_id,
            'resultType': self.result_type
        }
        
        logger.debug(f"查询参数: {params}")
        
        # 构建完整URL
        url = f"{lfasr_host}{api_get_result}?{urllib.parse.urlencode(params)}"
        
        # 轮询状态
        attempts = 0
        start_time = time.time()
        
        while attempts < self.max_retry:
            try:
                response = requests.get(url)
                
                # 检查HTTP状态
                if response.status_code != 200:
                    logger.warning(f"查询失败 HTTP {response.status_code} | 重试 #{attempts+1}")
                    attempts += 1
                    time.sleep(self.poll_interval)
                    continue
                
                result = response.json()
                
                # 检查API错误码
                if result.get('code') != 0:
                    error_msg = ERROR_CODES.get(result['code'], "未知错误")
                    logger.warning(f"查询失败: {error_msg} ({result['code']}) | 重试 #{attempts+1}")
                    attempts += 1
                    time.sleep(self.poll_interval)
                    continue
                
                # 检查转写状态
                status = result['content']['orderInfo']['status']
                logger.info(f"转写状态: {status} | 耗时: {int(time.time()-start_time)}秒")
                
                # 状态码说明: 
                # 0=待转写, 1=转写中, 2=完成, 3=部分结果, 4=全部完成, 5=失败
                if status == 4:  # 全部完成
                    logger.info("转写完成")
                    return result
                elif status in (0, 1, 3):  # 进行中
                    time.sleep(self.poll_interval)
                    continue
                elif status == 5:  # 失败
                    logger.error(f"转写失败: {result}")
                    raise Exception("转写失败")
                else:
                    logger.warning(f"未知状态: {status} | 重试 #{attempts+1}")
                    attempts += 1
                    time.sleep(self.poll_interval)
                    continue
                    
            except Exception as e:
                logger.error(f"查询失败: {str(e)} | 重试 #{attempts+1}")
                attempts += 1
                time.sleep(self.poll_interval)
        
        logger.error(f"获取结果失败，超过最大重试次数: {self.max_retry}")
        raise TimeoutError("获取转写结果超时")
    
    def transcribe(self, file_path, output_dir="results"):
        """
        完整转写流程: 上传->转写->保存结果
        
        :param file_path: 音频文件路径
        :param output_dir: 结果输出目录
        :return: 转写结果
        """
        logger.info(f"开始转写处理 | 文件: {file_path}")
        
        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)
        
        # 处理流程
        upload_result = self.upload_file(file_path)
        trans_result = self.get_transcription_result(upload_result)
        
        # 保存结果
        self.save_results(trans_result, file_path, output_dir)
        
        return trans_result
    
    def save_results(self, result, original_path, output_dir="results"):
        """
        保存转写结果
        
        :param result: 转写结果对象
        :param original_path: 原始音频文件路径
        :param output_dir: 输出目录
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        basename = os.path.splitext(os.path.basename(original_path))[0]
        
        # 1. 保存完整JSON结果
        json_filename = f"{output_dir}/{basename}_{timestamp}.json"
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=4)
        logger.info(f"完整结果已保存: {json_filename}")
        
        # 2. 提取并保存纯文本
        text_filename = f"{output_dir}/{basename}_{timestamp}.txt"
        transcript = self.extract_transcript_text(result)
        with open(text_filename, 'w', encoding='utf-8') as f:
            f.write(transcript)
        logger.info(f"纯文本已保存: {text_filename}")
        
        return transcript, text_filename, json_filename
    
    def extract_transcript_text(self, result):
        """从结果中提取转写文本"""
        try:
            order_result = json.loads(result['content']['orderResult'])
            segments = []
            
            # 解析不同格式的返回结果
            if "lattice" in order_result:
                # 标准格式
                for lattice in order_result["lattice"]:
                    best = lattice.get("json_1best", {})
                    st = best.get("st", {})
                    rts = st.get("rt", [])
                    
                    for rt in rts:
                        wss = rt.get("ws", [])
                        for ws in wss:
                            cws = ws.get("cw", [])
                            for cw in cws:
                                if "w" in cw:
                                    segments.append(cw["w"])
            elif "sentences" in order_result:
                # 另一种可能格式
                for sentence in order_result["sentences"]:
                    words = sentence.get("words", [])
                    for word in words:
                        if "w" in word:
                            segments.append(word["w"])
            else:
                logger.warning("无法识别的结果格式")
                return "无法解析转写结果"
            
            return "".join(segments)
        except Exception as e:
            logger.error(f"提取文本失败: {str(e)}")
            return "提取文本内容失败"

class AudioTranscriberApp:
    """语音转写应用程序GUI"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("讯飞语音转写助手 V1.0")
        self.root.geometry("900x700")
        self.root.iconbitmap(self.resource_path("app_icon.ico"))
        self.style = ttk.Style()
        
        # 配置日志
        self.log_text = None
        self.setup_logging()
        
        # 创建主界面
        self.create_main_frame()
        
        # 状态变量
        self.is_processing = False
        self.client = None
        self.current_transcript = ""
        
        # 检查配置文件
        self.load_config()
    
    def resource_path(self, relative_path):
        """获取资源文件的绝对路径，支持打包后资源文件访问"""
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")
        
        return os.path.join(base_path, relative_path)
    
    def setup_logging(self):
        """设置日志系统"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[self]
        )
        
    def handle(self, record):
        """处理日志记录"""
        if self.log_text:
            msg = self.format_record(record)
            self.append_to_log(msg)
    
    def format_record(self, record):
        """格式化日志记录"""
        return f"[{record.levelname}] {record.msg}"
    
    def append_to_log(self, message):
        """添加消息到日志控件"""
        if self.log_text:
            self.log_text.configure(state='normal')
            self.log_text.insert(tk.END, message + '\n')
            self.log_text.configure(state='disabled')
            self.log_text.see(tk.END)
    
    def create_main_frame(self):
        """创建主界面组件"""
        # 创建面板容器
        main_frame = ttk.Frame(self.root, padding=(20, 10))
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title_label = ttk.Label(
            main_frame, 
            text="讯飞语音转写助手", 
            font=("Segoe UI", 16, "bold"),
            foreground="#2c3e50"
        )
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        # 配置文件部分
        config_frame = ttk.LabelFrame(main_frame, text="API配置", padding=(10, 5))
        config_frame.grid(row=1, column=0, columnspan=2, sticky=tk.W+tk.E, pady=(0, 15))
        
        # APPID 标签和输入框
        appid_label = ttk.Label(config_frame, text="APPID:")
        appid_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 5), pady=5)
        self.appid_var = tk.StringVar()
        self.appid_entry = ttk.Entry(config_frame, textvariable=self.appid_var, width=40)
        self.appid_entry.grid(row=0, column=1, sticky=tk.W+tk.E, padx=(0, 10), pady=5)
        
        # SECRET_KEY 标签和输入框
        secret_label = ttk.Label(config_frame, text="SECRET_KEY:")
        secret_label.grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=5)
        self.secret_var = tk.StringVar()
        self.secret_entry = ttk.Entry(config_frame, textvariable=self.secret_var, width=40, show="*")
        self.secret_entry.grid(row=1, column=1, sticky=tk.W+tk.E, padx=(0, 10), pady=5)
        
        # 保存配置按钮
        self.save_button = ttk.Button(config_frame, text="保存配置", command=self.save_config)
        self.save_button.grid(row=1, column=2, padx=(5, 0), pady=5)
        
        # 文件选择部分
        file_frame = ttk.LabelFrame(main_frame, text="文件操作", padding=(10, 5))
        file_frame.grid(row=2, column=0, columnspan=2, sticky=tk.W+tk.E, pady=(0, 15))
        
        # 文件路径
        file_label = ttk.Label(file_frame, text="音频文件:")
        file_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 5), pady=5)
        self.file_path_var = tk.StringVar()
        self.file_entry = ttk.Entry(file_frame, textvariable=self.file_path_var, width=40, state='readonly')
        self.file_entry.grid(row=0, column=1, sticky=tk.W+tk.E, padx=(0, 10), pady=5)
        
        # 浏览文件按钮
        browse_button = ttk.Button(file_frame, text="浏览...", command=self.browse_audio_file)
        browse_button.grid(row=0, column=2, padx=(5, 0), pady=5)
        
        # 输出目录
        output_label = ttk.Label(file_frame, text="输出目录:")
        output_label.grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=5)
        self.output_dir_var = tk.StringVar()
        self.output_dir_var.set("转写结果")  # 默认值
        self.output_entry = ttk.Entry(file_frame, textvariable=self.output_dir_var, width=40)
        self.output_entry.grid(row=1, column=1, sticky=tk.W+tk.E, padx=(0, 10), pady=5)
        
        # 浏览输出目录按钮
        browse_output_button = ttk.Button(file_frame, text="浏览...", command=self.browse_output_dir)
        browse_output_button.grid(row=1, column=2, padx=(5, 0), pady=5)
        
        # 操作按钮
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=3, column=0, columnspan=2, pady=(10, 20))
        
        # 开始转写按钮
        self.transcribe_button = ttk.Button(
            button_frame, 
            text="开始转写", 
            command=self.start_transcription,
            style="Accent.TButton"
        )
        self.transcribe_button.grid(row=0, column=0, padx=10)
        
        # 复制文本按钮
        self.copy_button = ttk.Button(
            button_frame, 
            text="复制文本", 
            command=self.copy_transcript,
            state=tk.DISABLED
        )
        self.copy_button.grid(row=0, column=1, padx=10)
        
        # 清除日志按钮
        clear_log_button = ttk.Button(button_frame, text="清除日志", command=self.clear_log)
        clear_log_button.grid(row=0, column=2, padx=10)
        
        # 转写结果部分
        result_frame = ttk.LabelFrame(main_frame, text="转写结果", padding=(10, 5))
        result_frame.grid(row=4, column=0, columnspan=2, sticky=tk.W+tk.E+tk.N+tk.S, pady=(0, 15))
        
        # 结果文本框
        self.result_text = tk.Text(result_frame, wrap=tk.WORD, height=12, font=("Segoe UI", 10))
        self.result_text.grid(row=0, column=0, sticky=tk.W+tk.E+tk.N+tk.S)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.result_text.yview)
        scrollbar.grid(row=0, column=1, sticky=tk.N+tk.S)
        self.result_text.configure(yscrollcommand=scrollbar.set)
        
        # 日志部分
        log_frame = ttk.LabelFrame(main_frame, text="操作日志", padding=(10, 5))
        log_frame.grid(row=5, column=0, columnspan=2, sticky=tk.W+tk.E+tk.N+tk.S)
        
        # 日志文本框
        self.log_text = tk.Text(log_frame, wrap=tk.WORD, height=8, font=("Segoe UI", 9))
        self.log_text.grid(row=0, column=0, sticky=tk.W+tk.E+tk.N+tk.S)
        self.log_text.configure(state='disabled')
        
        # 添加滚动条
        log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scrollbar.grid(row=0, column=1, sticky=tk.N+tk.S)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        
        # 状态栏
        status_frame = ttk.Frame(main_frame)
        status_frame.grid(row=6, column=0, columnspan=2, sticky=tk.W+tk.E, pady=(10, 0))
        
        self.status_var = tk.StringVar()
        self.status_var.set("就绪")
        status_label = ttk.Label(status_frame, textvariable=self.status_var)
        status_label.pack(side=tk.LEFT)
        
        # 设置列和行权重
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(4, weight=1)
        main_frame.rowconfigure(5, weight=1)
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        # 设置窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 定义样式
        self.style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), foreground="white", background="#3498db")
        self.style.map("Accent.TButton", background=[("active", "#2980b9")])
    
    def load_config(self):
        """加载配置文件"""
        config_path = "config.json"
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.appid_var.set(config.get('appid', ''))
                    self.secret_var.set(config.get('secret_key', ''))
                    self.output_dir_var.set(config.get('output_dir', '转写结果'))
                    self.append_to_log("配置加载成功")
            except Exception as e:
                self.append_to_log(f"配置加载失败: {str(e)}")
        else:
            self.append_to_log("未找到配置文件，请填写配置后保存")
    
    def save_config(self):
        """保存配置到文件"""
        config = {
            'appid': self.appid_var.get(),
            'secret_key': self.secret_var.get(),
            'output_dir': self.output_dir_var.get()
        }
        
        try:
            with open("config.json", 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            self.append_to_log("配置已成功保存")
            messagebox.showinfo("成功", "配置已保存到config.json文件")
        except Exception as e:
            self.append_to_log(f"配置保存失败: {str(e)}")
            messagebox.showerror("错误", f"配置保存失败: {str(e)}")
    
    def browse_audio_file(self):
        """浏览选择音频文件"""
        file_types = [
            ('音频文件', '*.wav *.mp3 *.m4a *.amr'),
            ('WAV文件', '*.wav'),
            ('MP3文件', '*.mp3'),
            ('所有文件', '*.*')
        ]
        
        file_path = filedialog.askopenfilename(
            title="选择音频文件",
            filetypes=file_types
        )
        
        if file_path:
            self.file_path_var.set(file_path)
            self.append_to_log(f"已选择音频文件: {file_path}")
    
    def browse_output_dir(self):
        """浏览选择输出目录"""
        dir_path = filedialog.askdirectory(title="选择输出目录")
        
        if dir_path:
            self.output_dir_var.set(dir_path)
            self.append_to_log(f"已设置输出目录: {dir_path}")
    
    def start_transcription(self):
        """开始转写过程"""
        if self.is_processing:
            self.append_to_log("正在处理中，请稍候...")
            return
            
        appid = self.appid_var.get().strip()
        secret = self.secret_var.get().strip()
        file_path = self.file_path_var.get().strip()
        output_dir = self.output_dir_var.get().strip()
        
        # 验证输入
        if not appid or not secret:
            messagebox.showerror("错误", "请填写APPID和SECRET_KEY")
            return
            
        if not file_path:
            messagebox.showerror("错误", "请选择音频文件")
            return
            
        if not os.path.exists(file_path):
            messagebox.showerror("错误", "音频文件不存在")
            return
            
        # 更新状态
        self.is_processing = True
        self.transcribe_button.configure(text="处理中...", state=tk.DISABLED)
        self.copy_button.configure(state=tk.DISABLED)
        self.status_var.set("正在转写中...")
        self.result_text.delete(1.0, tk.END)
        self.append_to_log(f"开始处理音频文件: {os.path.basename(file_path)}")
        
        # 启动后台线程执行转写任务
        threading.Thread(target=self.run_transcription, args=(appid, secret, file_path, output_dir), daemon=True).start()
    
    def run_transcription(self, appid, secret, file_path, output_dir):
        """执行转写任务的线程函数"""
        try:
            # 初始化客户端
            self.client = LFASRClient(
                appid=appid,
                secret_key=secret,
                max_retry=3,
                poll_interval=5
            )
            
            # 执行转写
            result = self.client.transcribe(file_path, output_dir)
            transcript, text_file, json_file = self.client.save_results(result, file_path, output_dir)
            
            # 更新UI
            self.root.after(0, lambda: self.update_transcription_results(transcript, text_file, json_file))
            
        except Exception as e:
            error_msg = f"转写失败: {str(e)}"
            logger.error(error_msg)
            self.root.after(0, lambda: self.transcription_failed(error_msg))
        finally:
            self.is_processing = False
            self.root.after(0, lambda: self.transcribe_button.configure(text="开始转写", state=tk.NORMAL))
    
    def update_transcription_results(self, transcript, text_file, json_file):
        """更新转写结果到UI"""
        self.current_transcript = transcript
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, transcript)
        self.copy_button.configure(state=tk.NORMAL)
        
        # 显示成功信息
        msg = f"转写完成! 结果已保存: \n文本文件: {text_file}\nJSON文件: {json_file}"
        self.append_to_log(msg)
        self.status_var.set("转写完成")
        messagebox.showinfo("成功", msg)
    
    def transcription_failed(self, message):
        """处理转写失败情况"""
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, f"转写出错: {message}")
        self.status_var.set(message)
        self.append_to_log(f"转写失败: {message}")
        messagebox.showerror("错误", message)
    
    def copy_transcript(self):
        """复制转写文本到剪贴板"""
        if self.current_transcript:
            pyperclip.copy(self.current_transcript)
            self.append_to_log("文本已复制到剪贴板")
            self.status_var.set("文本已复制到剪贴板")
            messagebox.showinfo("成功", "转写文本已复制到剪贴板")
        else:
            self.append_to_log("没有可复制的文本内容")
    
    def clear_log(self):
        """清除日志"""
        if self.log_text:
            self.log_text.configure(state='normal')
            self.log_text.delete(1.0, tk.END)
            self.log_text.configure(state='disabled')
    
    def on_closing(self):
        """处理窗口关闭事件"""
        if self.is_processing:
            if messagebox.askyesno("确认退出", "转写仍在进行中，确定要退出吗?"):
                self.root.destroy()
        else:
            self.root.destroy()

# 初始化日志
def setup_logger():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # 文件处理器
    file_handler = logging.FileHandler("transcription.log", encoding='utf-8')
    file_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger

# 主函数
def main():
    # 设置日志
    global logger
    logger = setup_logger()
    
    try:
        root = tk.Tk()
        app = AudioTranscriberApp(root)
        root.mainloop()
    except Exception as e:
        logger.error(f"应用程序错误: {str(e)}")
        logger.error(traceback.format_exc())
        messagebox.showerror("致命错误", f"应用程序发生错误: {str(e)}")

if __name__ == "__main__":
    main()