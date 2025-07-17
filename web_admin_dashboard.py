# web_admin_dashboard.py - Веб-версия админ панели

import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import csv
from io import StringIO, BytesIO
import logging
import threading
import time

from flask import Flask, render_template, jsonify, request, send_file, redirect, url_for, Response
from flask_socketio import SocketIO, emit
import zipfile

# Импорты для работы с базой данных
from supabase import create_client, Client
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('admin_dashboard.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация Flask
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-change-in-production')
socketio = SocketIO(app, cors_allowed_origins="*")

class DatabaseManager:
    """Менеджер базы данных для веб-админки"""
    
    def __init__(self):
        try:
            # ИСПРАВЛЕНО: Используем правильную версию Supabase
            self.supabase: Client = create_client(
                os.getenv('SUPABASE_URL'),
                os.getenv('SUPABASE_KEY')
                # Убрали proxy аргумент
            )
            logger.info("✅ Connected to Supabase")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Supabase: {e}")
            self.supabase = None
    
    def get_users_stats(self) -> Dict:
        """Получить статистику пользователей"""
        if not self.supabase:
            return {}
            
        try:
            users = self.supabase.table('users').select('*').execute()
            
            total_users = len(users.data)
            active_users = len([u for u in users.data if u['daily_usage'] > 0])
            premium_users = len([u for u in users.data if u['subscription_tier'] != 'free'])
            
            # Группировка по датам регистрации (последние 30 дней)
            registrations_by_date = {}
            for user in users.data:
                date = user['created_at'][:10]  # YYYY-MM-DD
                registrations_by_date[date] = registrations_by_date.get(date, 0) + 1
            
            # Топ пользователи по активности
            top_users = sorted(users.data, key=lambda x: x['total_summaries'], reverse=True)[:10]
            
            return {
                'total_users': total_users,
                'active_users': active_users,
                'premium_users': premium_users,
                'registrations_by_date': registrations_by_date,
                'users_list': users.data,
                'top_users': top_users
            }
        except Exception as e:
            logger.error(f"Error getting users stats: {e}")
            return {}
    
    def get_analytics_data(self, days: int = 7) -> Dict:
        """Получить данные аналитики за период"""
        if not self.supabase:
            return {}
            
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
            
            # Проверяем существование таблиц аналитики
            events_data = []
            api_data = []
            conversions_data = []
            
            try:
                events = self.supabase.table('user_analytics').select('*').gte('timestamp', cutoff_date).execute()
                events_data = events.data
            except Exception as e:
                logger.warning(f"user_analytics table issue: {e}")
            
            try:
                api_usage = self.supabase.table('api_usage').select('*').gte('timestamp', cutoff_date).execute()
                api_data = api_usage.data
            except Exception as e:
                logger.warning(f"api_usage table issue: {e}")
            
            try:
                conversions = self.supabase.table('conversion_funnel').select('*').gte('timestamp', cutoff_date).execute()
                conversions_data = conversions.data
            except Exception as e:
                logger.warning(f"conversion_funnel table issue: {e}")
            
            # Обработка данных
            events_by_type = {}
            events_by_hour = {}
            events_by_day = {}
            total_cost = 0
            
            for event in events_data:
                event_type = event['event_type']
                events_by_type[event_type] = events_by_type.get(event_type, 0) + 1
                
                # По часам
                hour = event['timestamp'][:13]  # YYYY-MM-DDTHH
                events_by_hour[hour] = events_by_hour.get(hour, 0) + 1
                
                # По дням
                day = event['timestamp'][:10]  # YYYY-MM-DD
                events_by_day[day] = events_by_day.get(day, 0) + 1
                
                total_cost += float(event.get('cost_usd', 0))
            
            # API статистика
            api_stats = {}
            total_api_calls = 0
            total_api_cost = 0
            
            for usage in api_data:
                service = usage['service']
                if service not in api_stats:
                    api_stats[service] = {'calls': 0, 'cost': 0, 'errors': 0, 'avg_time': 0}
                
                api_stats[service]['calls'] += 1
                api_stats[service]['cost'] += float(usage.get('cost_usd', 0))
                api_stats[service]['avg_time'] += usage.get('processing_time_seconds', 0)
                
                if not usage.get('success', True):
                    api_stats[service]['errors'] += 1
                
                total_api_calls += 1
                total_api_cost += float(usage.get('cost_usd', 0))
            
            # Вычисляем средние значения
            for service in api_stats:
                if api_stats[service]['calls'] > 0:
                    api_stats[service]['avg_time'] /= api_stats[service]['calls']
            
            # Конверсионная воронка
            conversion_steps = {}
            for conv in conversions_data:
                step = conv['step']
                conversion_steps[step] = conversion_steps.get(step, 0) + 1
            
            return {
                'events_by_type': events_by_type,
                'events_by_hour': events_by_hour,
                'events_by_day': events_by_day,
                'total_cost': total_cost,
                'api_stats': api_stats,
                'total_api_calls': total_api_calls,
                'total_api_cost': total_api_cost,
                'conversion_steps': conversion_steps,
                'total_events': len(events_data),
                'period_days': days
            }
            
        except Exception as e:
            logger.error(f"Error getting analytics: {e}")
            return {}
    
    def test_connection(self) -> Dict:
        """Тест подключения к базе данных"""
        if not self.supabase:
            return {'success': False, 'error': 'Supabase not initialized'}
        
        try:
            # Тест основных таблиц
            tables_status = {}
            
            # Тест таблицы users
            try:
                result = self.supabase.table('users').select('count').limit(1).execute()
                tables_status['users'] = {'exists': True, 'count': len(result.data)}
            except Exception as e:
                tables_status['users'] = {'exists': False, 'error': str(e)}
            
            # Тест таблиц аналитики
            analytics_tables = ['user_analytics', 'user_sessions', 'api_usage', 'conversion_funnel']
            
            for table in analytics_tables:
                try:
                    result = self.supabase.table(table).select('count').limit(1).execute()
                    tables_status[table] = {'exists': True, 'count': len(result.data)}
                except Exception as e:
                    tables_status[table] = {'exists': False, 'error': str(e)}
            
            return {
                'success': True,
                'tables_status': tables_status,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}

# Инициализация менеджера БД
db_manager = DatabaseManager()

# ================================
# МАРШРУТЫ (ROUTES)
# ================================

@app.route('/')
def dashboard():
    """Главная страница дашборда"""
    return render_template('dashboard.html')

@app.route('/users')
def users():
    """Страница пользователей"""
    return render_template('users.html')

@app.route('/analytics')
def analytics():
    """Страница аналитики"""
    return render_template('analytics.html')

@app.route('/logs')
def logs():
    """Страница логов"""
    return render_template('logs.html')

@app.route('/settings')
def settings():
    """Страница настроек"""
    return render_template('settings.html')

# ================================
# API ENDPOINTS
# ================================

@app.route('/api/stats')
def api_stats():
    """API: Получить общую статистику"""
    try:
        users_stats = db_manager.get_users_stats()
        analytics_data = db_manager.get_analytics_data(7)  # Последние 7 дней
        
        combined_stats = {
            'users': users_stats,
            'analytics': analytics_data,
            'updated_at': datetime.now().isoformat()
        }
        
        return jsonify(combined_stats)
    except Exception as e:
        logger.error(f"Error in api_stats: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/users')
def api_users():
    """API: Получить список пользователей"""
    try:
        users_stats = db_manager.get_users_stats()
        return jsonify(users_stats)
    except Exception as e:
        logger.error(f"Error in api_users: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics')
def api_analytics():
    """API: Получить данные аналитики"""
    try:
        days = request.args.get('days', 7, type=int)
        analytics_data = db_manager.get_analytics_data(days)
        return jsonify(analytics_data)
    except Exception as e:
        logger.error(f"Error in api_analytics: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/logs')
def api_logs():
    """API: Получить логи"""
    try:
        # Читаем логи из файлов
        log_files = ['youtube_summarizer.log', 'admin_dashboard.log']
        all_logs = []
        
        for log_file in log_files:
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    # Берем последние 100 строк
                    for line in lines[-100:]:
                        all_logs.append({
                            'timestamp': datetime.now().isoformat(),
                            'file': log_file,
                            'message': line.strip()
                        })
        
        # Сортируем по времени
        all_logs.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return jsonify({
            'logs': all_logs[:200],  # Последние 200 записей
            'total': len(all_logs)
        })
        
    except Exception as e:
        logger.error(f"Error in api_logs: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/test-connection')
def api_test_connection():
    """API: Тест подключения к БД"""
    try:
        result = db_manager.test_connection()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error in test connection: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ================================
# ЭКСПОРТ ДАННЫХ
# ================================

@app.route('/export/users')
def export_users():
    """Экспорт пользователей в CSV"""
    try:
        users_stats = db_manager.get_users_stats()
        
        if not users_stats.get('users_list'):
            return jsonify({'error': 'No users data available'}), 404
        
        # Создаем CSV
        output = StringIO()
        writer = csv.writer(output)
        
        # Заголовки
        writer.writerow([
            'user_id', 'username', 'subscription_tier', 'subscription_expires',
            'daily_usage', 'total_summaries', 'created_at', 'last_payment'
        ])
        
        # Данные
        for user in users_stats['users_list']:
            writer.writerow([
                user['user_id'], user['username'], user['subscription_tier'],
                user['subscription_expires'], user['daily_usage'], 
                user['total_summaries'], user['created_at'], user.get('last_payment', '')
            ])
        
        # Подготавливаем ответ
        output.seek(0)
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=users_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'}
        )
        
    except Exception as e:
        logger.error(f"Error exporting users: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/export/analytics')
def export_analytics():
    """Экспорт аналитики в JSON"""
    try:
        days = request.args.get('days', 30, type=int)
        analytics_data = db_manager.get_analytics_data(days)
        
        # Подготавливаем JSON
        json_data = json.dumps(analytics_data, indent=2, ensure_ascii=False, default=str)
        
        return Response(
            json_data,
            mimetype='application/json',
            headers={'Content-Disposition': f'attachment; filename=analytics_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'}
        )
        
    except Exception as e:
        logger.error(f"Error exporting analytics: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/export/logs')
def export_logs():
    """Экспорт логов в TXT"""
    try:
        log_files = ['youtube_summarizer.log', 'admin_dashboard.log']
        all_logs = []
        
        for log_file in log_files:
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    all_logs.append(f"=== {log_file} ===\n{content}\n\n")
        
        combined_logs = '\n'.join(all_logs)
        
        return Response(
            combined_logs,
            mimetype='text/plain',
            headers={'Content-Disposition': f'attachment; filename=logs_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'}
        )
        
    except Exception as e:
        logger.error(f"Error exporting logs: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/export/all')
def export_all():
    """Экспорт всех данных в ZIP архиве"""
    try:
        # Создаем временный ZIP файл
        zip_buffer = BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Экспорт пользователей
            users_stats = db_manager.get_users_stats()
            if users_stats.get('users_list'):
                users_csv = StringIO()
                writer = csv.writer(users_csv)
                writer.writerow(['user_id', 'username', 'subscription_tier', 'daily_usage', 'total_summaries', 'created_at'])
                for user in users_stats['users_list']:
                    writer.writerow([user['user_id'], user['username'], user['subscription_tier'], 
                                   user['daily_usage'], user['total_summaries'], user['created_at']])
                zip_file.writestr('users.csv', users_csv.getvalue())
            
            # Экспорт аналитики
            analytics_data = db_manager.get_analytics_data(30)
            zip_file.writestr('analytics.json', json.dumps(analytics_data, indent=2, default=str))
            
            # Экспорт логов
            log_files = ['youtube_summarizer.log', 'admin_dashboard.log']
            for log_file in log_files:
                if os.path.exists(log_file):
                    zip_file.write(log_file)
        
        zip_buffer.seek(0)
        
        return send_file(
            BytesIO(zip_buffer.read()),
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'bot_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
        )
        
    except Exception as e:
        logger.error(f"Error creating full export: {e}")
        return jsonify({'error': str(e)}), 500

# ================================
# WEBSOCKET ДЛЯ REAL-TIME ОБНОВЛЕНИЙ
# ================================

def background_data_updates():
    """Фоновые обновления данных через WebSocket"""
    while True:
        try:
            # Получаем свежие данные
            users_stats = db_manager.get_users_stats()
            analytics_data = db_manager.get_analytics_data(7)
            
            # Отправляем всем подключенным клиентам
            socketio.emit('data_update', {
                'users': users_stats,
                'analytics': analytics_data,
                'timestamp': datetime.now().isoformat()
            })
            
            # Ждем 30 секунд
            time.sleep(30)
            
        except Exception as e:
            logger.error(f"Error in background updates: {e}")
            time.sleep(60)  # Увеличиваем интервал при ошибке

@socketio.on('connect')
def handle_connect():
    """Обработка подключения клиента"""
    logger.info("Client connected to WebSocket")
    emit('status', {'message': 'Connected to admin dashboard'})

@socketio.on('disconnect')
def handle_disconnect():
    """Обработка отключения клиента"""
    logger.info("Client disconnected from WebSocket")

@socketio.on('request_update')
def handle_request_update():
    """Принудительное обновление данных по запросу"""
    try:
        users_stats = db_manager.get_users_stats()
        analytics_data = db_manager.get_analytics_data(7)
        
        emit('data_update', {
            'users': users_stats,
            'analytics': analytics_data,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error in manual update: {e}")
        emit('error', {'message': str(e)})

# ================================
# СОЗДАНИЕ HTML ШАБЛОНОВ
# ================================

def create_templates():
    """Создать HTML шаблоны"""
    templates_dir = 'templates'
    static_dir = 'static'
    
    os.makedirs(templates_dir, exist_ok=True)
    os.makedirs(static_dir, exist_ok=True)
    
    # Базовый шаблон
    base_template = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Admin Dashboard{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        .sidebar {
            min-height: 100vh;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        .card {
            border: none;
            border-radius: 15px;
            box-shadow: 0 0 20px rgba(0,0,0,0.1);
        }
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .nav-link {
            color: white !important;
            border-radius: 10px;
            margin: 5px 0;
        }
        .nav-link:hover {
            background-color: rgba(255,255,255,0.2);
        }
        .nav-link.active {
            background-color: rgba(255,255,255,0.3);
        }
    </style>
</head>
<body>
    <div class="container-fluid">
        <div class="row">
            <!-- Сайдбар -->
            <nav class="col-md-3 col-lg-2 d-md-block sidebar collapse">
                <div class="position-sticky pt-3">
                    <div class="text-center mb-4">
                        <h4 class="text-white">📊 Admin Panel</h4>
                        <small class="text-light">YouTube Summarizer Bot</small>
                    </div>
                    
                    <ul class="nav flex-column">
                        <li class="nav-item">
                            <a class="nav-link" href="/">
                                <i class="fas fa-tachometer-alt"></i> Дашборд
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="/users">
                                <i class="fas fa-users"></i> Пользователи
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="/analytics">
                                <i class="fas fa-chart-line"></i> Аналитика
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="/logs">
                                <i class="fas fa-file-text"></i> Логи
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="/settings">
                                <i class="fas fa-cog"></i> Настройки
                            </a>
                        </li>
                    </ul>
                    
                    <hr class="text-white">
                    
                    <div class="text-center">
                        <small class="text-light">
                            <div id="connection-status">🔴 Подключение...</div>
                            <div id="last-update">Обновление...</div>
                        </small>
                    </div>
                </div>
            </nav>
            
            <!-- Основной контент -->
            <main class="col-md-9 ms-sm-auto col-lg-10 px-md-4">
                <div class="pt-3">
                    {% block content %}{% endblock %}
                </div>
            </main>
        </div>
    </div>
    
    <!-- WebSocket подключение -->
    <script>
        const socket = io();
        
        socket.on('connect', function() {
            document.getElementById('connection-status').innerHTML = '🟢 Подключено';
        });
        
        socket.on('disconnect', function() {
            document.getElementById('connection-status').innerHTML = '🔴 Отключено';
        });
        
        socket.on('data_update', function(data) {
            document.getElementById('last-update').innerHTML = 
                'Обновлено: ' + new Date(data.timestamp).toLocaleTimeString();
            
            // Обновляем данные на странице
            if (typeof updatePageData === 'function') {
                updatePageData(data);
            }
        });
        
        // Запрос обновления каждые 30 секунд
        setInterval(() => {
            socket.emit('request_update');
        }, 30000);
    </script>
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html>'''
    
    # Дашборд
    dashboard_template = '''{% extends "base.html" %}

{% block title %}Дашборд - Admin Panel{% endblock %}

{% block content %}
<div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
    <h1 class="h2">📊 Дашборд</h1>
    <div class="btn-toolbar mb-2 mb-md-0">
        <button class="btn btn-primary" onclick="refreshData()">
            <i class="fas fa-sync-alt"></i> Обновить
        </button>
    </div>
</div>

<!-- Статистика -->
<div class="row mb-4">
    <div class="col-md-3">
        <div class="card stat-card">
            <div class="card-body text-center">
                <i class="fas fa-users fa-2x mb-2"></i>
                <h3 id="total-users">0</h3>
                <p>Всего пользователей</p>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card stat-card">
            <div class="card-body text-center">
                <i class="fas fa-user-check fa-2x mb-2"></i>
                <h3 id="active-users">0</h3>
                <p>Активные сегодня</p>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card stat-card">
            <div class="card-body text-center">
                <i class="fas fa-crown fa-2x mb-2"></i>
                <h3 id="premium-users">0</h3>
                <p>Premium подписки</p>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card stat-card">
            <div class="card-body text-center">
                <i class="fas fa-dollar-sign fa-2x mb-2"></i>
                <h3 id="total-cost">$0.00</h3>
                <p>Общие затраты</p>
            </div>
        </div>
    </div>
</div>

<!-- Графики -->
<div class="row">
    <div class="col-md-6">
        <div class="card">
            <div class="card-header">
                <h5>События по типам</h5>
            </div>
            <div class="card-body">
                <canvas id="eventsChart"></canvas>
            </div>
        </div>
    </div>
    <div class="col-md-6">
        <div class="card">
            <div class="card-header">
                <h5>Активность по дням</h5>
            </div>
            <div class="card-body">
                <canvas id="activityChart"></canvas>
            </div>
        </div>
    </div>
</div>

<script>
let eventsChart, activityChart;

function initCharts() {
    // График событий
    const eventsCtx = document.getElementById('eventsChart').getContext('2d');
    eventsChart = new Chart(eventsCtx, {
        type: 'doughnut',
        data: {
            labels: [],
            datasets: [{
                data: [],
                backgroundColor: ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF']
            }]
        }
    });
    
    // График активности
    const activityCtx = document.getElementById('activityChart').getContext('2d');
    activityChart = new Chart(activityCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'События',
                data: [],
                borderColor: '#36A2EB',
                fill: false
            }]
        }
    });
}

function updatePageData(data) {
    // Обновляем статистику
    if (data.users) {
        document.getElementById('total-users').textContent = data.users.total_users || 0;
        document.getElementById('active-users').textContent = data.users.active_users || 0;
        document.getElementById('premium-users').textContent = data.users.premium_users || 0;
    }
    
    if (data.analytics) {
        document.getElementById('total-cost').textContent = '$' + (data.analytics.total_cost || 0).toFixed(2);
        
        // Обновляем графики
        if (data.analytics.events_by_type) {
            eventsChart.data.labels = Object.keys(data.analytics.events_by_type);
            eventsChart.data.datasets[0].data = Object.values(data.analytics.events_by_type);
            eventsChart.update();
        }
        
        if (data.analytics.events_by_day) {
            activityChart.data.labels = Object.keys(data.analytics.events_by_day);
            activityChart.data.datasets[0].data = Object.values(data.analytics.events_by_day);
            activityChart.update();
        }
    }
}

function refreshData() {
    fetch('/api/stats')
        .then(response => response.json())
        .then(data => updatePageData(data))
        .catch(error => console.error('Error:', error));
}

// Инициализация при загрузке
document.addEventListener('DOMContentLoaded', function() {
    initCharts();
    refreshData();
});
</script>
{% endblock %}'''

    # Сохраняем шаблоны
    with open(os.path.join(templates_dir, 'base.html'), 'w', encoding='utf-8') as f:
        f.write(base_template)
    
    with open(os.path.join(templates_dir, 'dashboard.html'), 'w', encoding='utf-8') as f:
        f.write(dashboard_template)
    
    # Шаблон пользователей
    users_template = '''{% extends "base.html" %}

{% block title %}Пользователи - Admin Panel{% endblock %}

{% block content %}
<div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
    <h1 class="h2">👥 Пользователи</h1>
    <div class="btn-toolbar mb-2 mb-md-0">
        <a href="/export/users" class="btn btn-outline-primary me-2">
            <i class="fas fa-download"></i> Экспорт CSV
        </a>
        <button class="btn btn-primary" onclick="refreshUsers()">
            <i class="fas fa-sync-alt"></i> Обновить
        </button>
    </div>
</div>

<!-- Фильтры -->
<div class="card mb-4">
    <div class="card-body">
        <div class="row">
            <div class="col-md-3">
                <select class="form-select" id="tierFilter">
                    <option value="">Все подписки</option>
                    <option value="free">Free</option>
                    <option value="premium">Premium</option>
                    <option value="enterprise">Enterprise</option>
                </select>
            </div>
            <div class="col-md-3">
                <input type="text" class="form-control" id="searchInput" placeholder="Поиск по имени...">
            </div>
            <div class="col-md-3">
                <select class="form-select" id="sortBy">
                    <option value="created_at">По дате создания</option>
                    <option value="total_summaries">По активности</option>
                    <option value="daily_usage">По использованию</option>
                </select>
            </div>
            <div class="col-md-3">
                <button class="btn btn-secondary" onclick="applyFilters()">Применить</button>
            </div>
        </div>
    </div>
</div>

<!-- Таблица пользователей -->
<div class="card">
    <div class="card-body">
        <div class="table-responsive">
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Username</th>
                        <th>Подписка</th>
                        <th>Использование</th>
                        <th>Всего обработано</th>
                        <th>Создан</th>
                        <th>Действия</th>
                    </tr>
                </thead>
                <tbody id="usersTableBody">
                    <tr>
                        <td colspan="7" class="text-center">Загрузка...</td>
                    </tr>
                </tbody>
            </table>
        </div>
        
        <div id="usersPagination" class="d-flex justify-content-center mt-3">
            <!-- Пагинация будет добавлена через JS -->
        </div>
    </div>
</div>

<script>
let allUsers = [];
let filteredUsers = [];
let currentPage = 1;
const usersPerPage = 20;

function updatePageData(data) {
    if (data.users && data.users.users_list) {
        allUsers = data.users.users_list;
        applyFilters();
    }
}

function refreshUsers() {
    fetch('/api/users')
        .then(response => response.json())
        .then(data => {
            allUsers = data.users_list || [];
            applyFilters();
        })
        .catch(error => console.error('Error:', error));
}

function applyFilters() {
    const tierFilter = document.getElementById('tierFilter').value;
    const searchInput = document.getElementById('searchInput').value.toLowerCase();
    const sortBy = document.getElementById('sortBy').value;
    
    // Фильтрация
    filteredUsers = allUsers.filter(user => {
        const matchesTier = !tierFilter || user.subscription_tier === tierFilter;
        const matchesSearch = !searchInput || user.username.toLowerCase().includes(searchInput);
        return matchesTier && matchesSearch;
    });
    
    // Сортировка
    filteredUsers.sort((a, b) => {
        if (sortBy === 'created_at') {
            return new Date(b.created_at) - new Date(a.created_at);
        } else if (sortBy === 'total_summaries') {
            return b.total_summaries - a.total_summaries;
        } else if (sortBy === 'daily_usage') {
            return b.daily_usage - a.daily_usage;
        }
        return 0;
    });
    
    currentPage = 1;
    displayUsers();
}

function displayUsers() {
    const tbody = document.getElementById('usersTableBody');
    const startIndex = (currentPage - 1) * usersPerPage;
    const endIndex = startIndex + usersPerPage;
    const pageUsers = filteredUsers.slice(startIndex, endIndex);
    
    if (pageUsers.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center">Пользователи не найдены</td></tr>';
        return;
    }
    
    tbody.innerHTML = pageUsers.map(user => `
        <tr>
            <td>${user.user_id}</td>
            <td>
                <div class="d-flex align-items-center">
                    <div class="avatar-placeholder me-2">👤</div>
                    ${user.username}
                </div>
            </td>
            <td>
                <span class="badge ${getBadgeClass(user.subscription_tier)}">
                    ${user.subscription_tier}
                </span>
            </td>
            <td>${user.daily_usage}</td>
            <td>${user.total_summaries}</td>
            <td>${new Date(user.created_at).toLocaleDateString()}</td>
            <td>
                <button class="btn btn-sm btn-outline-primary" onclick="viewUser(${user.user_id})">
                    <i class="fas fa-eye"></i>
                </button>
            </td>
        </tr>
    `).join('');
    
    updatePagination();
}

function getBadgeClass(tier) {
    switch(tier) {
        case 'premium': return 'bg-warning';
        case 'enterprise': return 'bg-success';
        default: return 'bg-secondary';
    }
}

function updatePagination() {
    const totalPages = Math.ceil(filteredUsers.length / usersPerPage);
    const pagination = document.getElementById('usersPagination');
    
    if (totalPages <= 1) {
        pagination.innerHTML = '';
        return;
    }
    
    let paginationHTML = '<nav><ul class="pagination">';
    
    // Предыдущая
    paginationHTML += `
        <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="changePage(${currentPage - 1})">Назад</a>
        </li>
    `;
    
    // Страницы
    for (let i = 1; i <= totalPages; i++) {
        if (i === currentPage || i === 1 || i === totalPages || (i >= currentPage - 1 && i <= currentPage + 1)) {
            paginationHTML += `
                <li class="page-item ${i === currentPage ? 'active' : ''}">
                    <a class="page-link" href="#" onclick="changePage(${i})">${i}</a>
                </li>
            `;
        } else if (i === currentPage - 2 || i === currentPage + 2) {
            paginationHTML += '<li class="page-item disabled"><span class="page-link">...</span></li>';
        }
    }
    
    // Следующая
    paginationHTML += `
        <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="changePage(${currentPage + 1})">Вперед</a>
        </li>
    `;
    
    paginationHTML += '</ul></nav>';
    pagination.innerHTML = paginationHTML;
}

function changePage(page) {
    const totalPages = Math.ceil(filteredUsers.length / usersPerPage);
    if (page >= 1 && page <= totalPages) {
        currentPage = page;
        displayUsers();
    }
}

function viewUser(userId) {
    const user = allUsers.find(u => u.user_id === userId);
    if (user) {
        alert(`Пользователь: ${user.username}\\nID: ${user.user_id}\\nПодписка: ${user.subscription_tier}\\nОбработано: ${user.total_summaries}`);
    }
}

// Обработчики событий
document.getElementById('searchInput').addEventListener('input', applyFilters);
document.getElementById('tierFilter').addEventListener('change', applyFilters);

// Инициализация
document.addEventListener('DOMContentLoaded', function() {
    refreshUsers();
});
</script>
{% endblock %}'''

    with open(os.path.join(templates_dir, 'users.html'), 'w', encoding='utf-8') as f:
        f.write(users_template)

    # Шаблон аналитики
    analytics_template = '''{% extends "base.html" %}

{% block title %}Аналитика - Admin Panel{% endblock %}

{% block content %}
<div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
    <h1 class="h2">📈 Аналитика</h1>
    <div class="btn-toolbar mb-2 mb-md-0">
        <select class="form-select me-2" id="periodSelect" style="width: auto;">
            <option value="1">Последний день</option>
            <option value="7" selected>Последние 7 дней</option>
            <option value="30">Последние 30 дней</option>
        </select>
        <a href="/export/analytics" class="btn btn-outline-primary me-2">
            <i class="fas fa-download"></i> Экспорт JSON
        </a>
        <button class="btn btn-primary" onclick="refreshAnalytics()">
            <i class="fas fa-sync-alt"></i> Обновить
        </button>
    </div>
</div>

<!-- Метрики -->
<div class="row mb-4">
    <div class="col-md-3">
        <div class="card text-center">
            <div class="card-body">
                <h3 id="totalEvents">0</h3>
                <p class="text-muted">Всего событий</p>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card text-center">
            <div class="card-body">
                <h3 id="totalApiCalls">0</h3>
                <p class="text-muted">API вызовов</p>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card text-center">
            <div class="card-body">
                <h3 id="totalApiCost">$0.00</h3>
                <p class="text-muted">Затраты на API</p>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card text-center">
            <div class="card-body">
                <h3 id="periodDays">7</h3>
                <p class="text-muted">Дней в периоде</p>
            </div>
        </div>
    </div>
</div>

<!-- Графики -->
<div class="row mb-4">
    <div class="col-md-8">
        <div class="card">
            <div class="card-header">
                <h5>Активность по дням</h5>
            </div>
            <div class="card-body">
                <canvas id="timelineChart" height="100"></canvas>
            </div>
        </div>
    </div>
    <div class="col-md-4">
        <div class="card">
            <div class="card-header">
                <h5>События по типам</h5>
            </div>
            <div class="card-body">
                <canvas id="eventsTypeChart"></canvas>
            </div>
        </div>
    </div>
</div>

<!-- API статистика -->
<div class="row mb-4">
    <div class="col-md-6">
        <div class="card">
            <div class="card-header">
                <h5>API Статистика</h5>
            </div>
            <div class="card-body">
                <div id="apiStatsTable">
                    <p class="text-muted">Загрузка...</p>
                </div>
            </div>
        </div>
    </div>
    <div class="col-md-6">
        <div class="card">
            <div class="card-header">
                <h5>Конверсионная воронка</h5>
            </div>
            <div class="card-body">
                <canvas id="funnelChart"></canvas>
            </div>
        </div>
    </div>
</div>

<script>
let timelineChart, eventsTypeChart, funnelChart;

function initAnalyticsCharts() {
    // График активности по времени
    const timelineCtx = document.getElementById('timelineChart').getContext('2d');
    timelineChart = new Chart(timelineCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'События',
                data: [],
                borderColor: '#36A2EB',
                backgroundColor: 'rgba(54, 162, 235, 0.1)',
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });
    
    // График типов событий
    const eventsTypeCtx = document.getElementById('eventsTypeChart').getContext('2d');
    eventsTypeChart = new Chart(eventsTypeCtx, {
        type: 'doughnut',
        data: {
            labels: [],
            datasets: [{
                data: [],
                backgroundColor: [
                    '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', 
                    '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF'
                ]
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false
        }
    });
    
    // График воронки
    const funnelCtx = document.getElementById('funnelChart').getContext('2d');
    funnelChart = new Chart(funnelCtx, {
        type: 'bar',
        data: {
            labels: [],
            datasets: [{
                label: 'Пользователи',
                data: [],
                backgroundColor: '#4BC0C0'
            }]
        },
        options: {
            responsive: true,
            indexAxis: 'y'
        }
    });
}

function updateAnalyticsData(data) {
    if (!data) return;
    
    // Обновляем метрики
    document.getElementById('totalEvents').textContent = data.total_events || 0;
    document.getElementById('totalApiCalls').textContent = data.total_api_calls || 0;
    document.getElementById('totalApiCost').textContent = ' + (data.total_api_cost || 0).toFixed(2);
    document.getElementById('periodDays').textContent = data.period_days || 7;
    
    // Обновляем график активности
    if (data.events_by_day) {
        const sortedDays = Object.keys(data.events_by_day).sort();
        timelineChart.data.labels = sortedDays;
        timelineChart.data.datasets[0].data = sortedDays.map(day => data.events_by_day[day]);
        timelineChart.update();
    }
    
    // Обновляем график типов событий
    if (data.events_by_type) {
        eventsTypeChart.data.labels = Object.keys(data.events_by_type);
        eventsTypeChart.data.datasets[0].data = Object.values(data.events_by_type);
        eventsTypeChart.update();
    }
    
    // Обновляем воронку
    if (data.conversion_steps) {
        funnelChart.data.labels = Object.keys(data.conversion_steps);
        funnelChart.data.datasets[0].data = Object.values(data.conversion_steps);
        funnelChart.update();
    }
    
    // Обновляем API статистику
    updateApiStatsTable(data.api_stats || {});
}

function updateApiStatsTable(apiStats) {
    const container = document.getElementById('apiStatsTable');
    
    if (Object.keys(apiStats).length === 0) {
        container.innerHTML = '<p class="text-muted">Нет данных об API</p>';
        return;
    }
    
    let tableHTML = `
        <div class="table-responsive">
            <table class="table table-sm">
                <thead>
                    <tr>
                        <th>Сервис</th>
                        <th>Вызовы</th>
                        <th>Стоимость</th>
                        <th>Ошибки</th>
                        <th>Ср. время</th>
                    </tr>
                </thead>
                <tbody>
    `;
    
    for (const [service, stats] of Object.entries(apiStats)) {
        tableHTML += `
            <tr>
                <td><strong>${service}</strong></td>
                <td>${stats.calls}</td>
                <td>${stats.cost.toFixed(4)}</td>
                <td>${stats.errors || 0}</td>
                <td>${stats.avg_time ? stats.avg_time.toFixed(1) + 's' : 'N/A'}</td>
            </tr>
        `;
    }
    
    tableHTML += '</tbody></table></div>';
    container.innerHTML = tableHTML;
}

function refreshAnalytics() {
    const period = document.getElementById('periodSelect').value;
    fetch(`/api/analytics?days=${period}`)
        .then(response => response.json())
        .then(data => updateAnalyticsData(data))
        .catch(error => console.error('Error:', error));
}

// Обработчик изменения периода
document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('periodSelect').addEventListener('change', refreshAnalytics);
    initAnalyticsCharts();
    refreshAnalytics();
});
</script>
{% endblock %}'''

    with open(os.path.join(templates_dir, 'analytics.html'), 'w', encoding='utf-8') as f:
        f.write(analytics_template)

    # Шаблон логов
    logs_template = '''{% extends "base.html" %}

{% block title %}Логи - Admin Panel{% endblock %}

{% block content %}
<div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
    <h1 class="h2">📝 Логи системы</h1>
    <div class="btn-toolbar mb-2 mb-md-0">
        <a href="/export/logs" class="btn btn-outline-primary me-2">
            <i class="fas fa-download"></i> Экспорт
        </a>
        <button class="btn btn-secondary me-2" onclick="clearLogs()">
            <i class="fas fa-trash"></i> Очистить
        </button>
        <button class="btn btn-primary" onclick="refreshLogs()">
            <i class="fas fa-sync-alt"></i> Обновить
        </button>
    </div>
</div>

<!-- Фильтры -->
<div class="card mb-4">
    <div class="card-body">
        <div class="row">
            <div class="col-md-3">
                <select class="form-select" id="logFileFilter">
                    <option value="">Все файлы</option>
                    <option value="youtube_summarizer.log">Bot Logs</option>
                    <option value="admin_dashboard.log">Admin Logs</option>
                </select>
            </div>
            <div class="col-md-3">
                <select class="form-select" id="logLevelFilter">
                    <option value="">Все уровни</option>
                    <option value="ERROR">ERROR</option>
                    <option value="WARNING">WARNING</option>
                    <option value="INFO">INFO</option>
                    <option value="DEBUG">DEBUG</option>
                </select>
            </div>
            <div class="col-md-4">
                <input type="text" class="form-control" id="logSearchInput" placeholder="Поиск в логах...">
            </div>
            <div class="col-md-2">
                <button class="btn btn-secondary" onclick="applyLogFilters()">Применить</button>
            </div>
        </div>
    </div>
</div>

<!-- Логи -->
<div class="card">
    <div class="card-body">
        <div class="form-check mb-3">
            <input class="form-check-input" type="checkbox" id="autoRefresh" checked>
            <label class="form-check-label" for="autoRefresh">
                Автообновление (каждые 5 секунд)
            </label>
        </div>
        
        <div id="logsContainer" style="height: 500px; overflow-y: auto; background-color: #1e1e1e; color: #ffffff; padding: 15px; border-radius: 5px; font-family: 'Courier New', monospace; font-size: 12px;">
            <div class="text-center text-muted">Загрузка логов...</div>
        </div>
        
        <div class="mt-3">
            <small class="text-muted">
                Показано последних <span id="logsCount">0</span> записей
            </small>
        </div>
    </div>
</div>

<script>
let allLogs = [];
let filteredLogs = [];
let autoRefreshInterval;

function refreshLogs() {
    fetch('/api/logs')
        .then(response => response.json())
        .then(data => {
            allLogs = data.logs || [];
            applyLogFilters();
            document.getElementById('logsCount').textContent = allLogs.length;
        })
        .catch(error => {
            console.error('Error:', error);
            document.getElementById('logsContainer').innerHTML = 
                '<div class="text-danger">Ошибка загрузки логов: ' + error.message + '</div>';
        });
}

function applyLogFilters() {
    const fileFilter = document.getElementById('logFileFilter').value;
    const levelFilter = document.getElementById('logLevelFilter').value;
    const searchInput = document.getElementById('logSearchInput').value.toLowerCase();
    
    filteredLogs = allLogs.filter(log => {
        const matchesFile = !fileFilter || log.file === fileFilter;
        const matchesLevel = !levelFilter || log.message.includes(levelFilter);
        const matchesSearch = !searchInput || log.message.toLowerCase().includes(searchInput);
        return matchesFile && matchesLevel && matchesSearch;
    });
    
    displayLogs();
}

function displayLogs() {
    const container = document.getElementById('logsContainer');
    
    if (filteredLogs.length === 0) {
        container.innerHTML = '<div class="text-muted">Логи не найдены</div>';
        return;
    }
    
    const logsHTML = filteredLogs.map(log => {
        let colorClass = '';
        if (log.message.includes('ERROR')) colorClass = 'text-danger';
        else if (log.message.includes('WARNING')) colorClass = 'text-warning';
        else if (log.message.includes('INFO')) colorClass = 'text-info';
        
        return `<div class="${colorClass}">[${log.file}] ${log.message}</div>`;
    }).join('');
    
    container.innerHTML = logsHTML;
    
    // Прокрутка вниз
    container.scrollTop = container.scrollHeight;
}

function clearLogs() {
    document.getElementById('logsContainer').innerHTML = '<div class="text-muted">Логи очищены</div>';
    allLogs = [];
    filteredLogs = [];
    document.getElementById('logsCount').textContent = '0';
}

function toggleAutoRefresh() {
    const autoRefresh = document.getElementById('autoRefresh').checked;
    
    if (autoRefresh) {
        autoRefreshInterval = setInterval(refreshLogs, 5000);
    } else {
        if (autoRefreshInterval) {
            clearInterval(autoRefreshInterval);
        }
    }
}

// Обработчики событий
document.getElementById('autoRefresh').addEventListener('change', toggleAutoRefresh);
document.getElementById('logSearchInput').addEventListener('input', applyLogFilters);
document.getElementById('logFileFilter').addEventListener('change', applyLogFilters);
document.getElementById('logLevelFilter').addEventListener('change', applyLogFilters);

// Инициализация
document.addEventListener('DOMContentLoaded', function() {
    refreshLogs();
    toggleAutoRefresh();
});
</script>
{% endblock %}'''

    with open(os.path.join(templates_dir, 'logs.html'), 'w', encoding='utf-8') as f:
        f.write(logs_template)

    # Шаблон настроек
    settings_template = '''{% extends "base.html" %}

{% block title %}Настройки - Admin Panel{% endblock %}

{% block content %}
<div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
    <h1 class="h2">⚙️ Настройки</h1>
</div>

<div class="row">
    <div class="col-md-6">
        <!-- База данных -->
        <div class="card mb-4">
            <div class="card-header">
                <h5>🗄️ База данных</h5>
            </div>
            <div class="card-body">
                <div class="mb-3">
                    <label class="form-label">Supabase URL:</label>
                    <input type="text" class="form-control" id="supabaseUrl" readonly>
                </div>
                
                <button class="btn btn-primary" onclick="testConnection()">
                    <i class="fas fa-plug"></i> Тест подключения
                </button>
                
                <div id="connectionResult" class="mt-3"></div>
            </div>
        </div>
        
        <!-- Экспорт -->
        <div class="card mb-4">
            <div class="card-header">
                <h5>📁 Экспорт данных</h5>
            </div>
            <div class="card-body">
                <div class="d-grid gap-2">
                    <a href="/export/users" class="btn btn-outline-primary">
                        <i class="fas fa-users"></i> Экспорт пользователей (CSV)
                    </a>
                    <a href="/export/analytics" class="btn btn-outline-info">
                        <i class="fas fa-chart-line"></i> Экспорт аналитики (JSON)
                    </a>
                    <a href="/export/logs" class="btn btn-outline-warning">
                        <i class="fas fa-file-text"></i> Экспорт логов (TXT)
                    </a>
                    <a href="/export/all" class="btn btn-success">
                        <i class="fas fa-archive"></i> Полный экспорт (ZIP)
                    </a>
                </div>
            </div>
        </div>
    </div>
    
    <div class="col-md-6">
        <!-- Система -->
        <div class="card mb-4">
            <div class="card-header">
                <h5>💻 Система</h5>
            </div>
            <div class="card-body">
                <div class="row text-center">
                    <div class="col-6">
                        <h4 id="systemCpu">N/A</h4>
                        <small class="text-muted">CPU</small>
                    </div>
                    <div class="col-6">
                        <h4 id="systemMemory">N/A</h4>
                        <small class="text-muted">Память</small>
                    </div>
                </div>
                
                <hr>
                
                <div class="text-center">
                    <h5 id="systemStatus">🟢 Система работает</h5>
                    <small class="text-muted">Последняя проверка: <span id="lastCheck">--:--</span></small>
                </div>
            </div>
        </div>
        
        <!-- Информация -->
        <div class="card mb-4">
            <div class="card-header">
                <h5>ℹ️ Информация</h5>
            </div>
            <div class="card-body">
                <div class="mb-2">
                    <strong>Версия:</strong> 1.0.0
                </div>
                <div class="mb-2">
                    <strong>Последний запуск:</strong> <span id="lastStart">Загрузка...</span>
                </div>
                <div class="mb-2">
                    <strong>Автор:</strong> YouTube Summarizer Bot Team
                </div>
                <div class="mb-2">
                    <strong>GitHub:</strong> <a href="#" target="_blank">Repository</a>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
function testConnection() {
    const button = event.target;
    const resultDiv = document.getElementById('connectionResult');
    
    button.disabled = true;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Тестирование...';
    
    fetch('/api/test-connection')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                resultDiv.innerHTML = `
                    <div class="alert alert-success">
                        <strong>✅ Подключение успешно!</strong><br>
                        <small>Проверено в: ${new Date(data.timestamp).toLocaleString()}</small>
                        
                        <div class="mt-2">
                            <strong>Статус таблиц:</strong>
                            <ul class="list-unstyled mt-1">
                                ${Object.entries(data.tables_status).map(([table, status]) => 
                                    `<li>${status.exists ? '✅' : '❌'} ${table} ${status.exists ? '(' + (status.count || 0) + ' записей)' : ''}</li>`
                                ).join('')}
                            </ul>
                        </div>
                    </div>
                `;
            } else {
                resultDiv.innerHTML = `
                    <div class="alert alert-danger">
                        <strong>❌ Ошибка подключения!</strong><br>
                        <small>${data.error}</small>
                    </div>
                `;
            }
        })
        .catch(error => {
            resultDiv.innerHTML = `
                <div class="alert alert-danger">
                    <strong>❌ Ошибка!</strong><br>
                    <small>${error.message}</small>
                </div>
            `;
        })
        .finally(() => {
            button.disabled = false;
            button.innerHTML = '<i class="fas fa-plug"></i> Тест подключения';
        });
}

function updateSystemInfo() {
    // Обновляем время последней проверки
    document.getElementById('lastCheck').textContent = new Date().toLocaleTimeString();
    
    // Можно добавить реальные системные метрики, если они доступны
    document.getElementById('systemCpu').textContent = 'N/A';
    document.getElementById('systemMemory').textContent = 'N/A';
}

// Инициализация
document.addEventListener('DOMContentLoaded', function() {
    // Заполняем URL базы данных (скрыв ключ)
    const url = '${os.getenv("SUPABASE_URL", "Не настроено")}';
    document.getElementById('supabaseUrl').value = url;
    
    // Время запуска
    document.getElementById('lastStart').textContent = new Date().toLocaleString();
    
    // Обновляем системную информацию
    updateSystemInfo();
    setInterval(updateSystemInfo, 30000); // Каждые 30 секунд
});
</script>
{% endblock %}'''

    with open(os.path.join(templates_dir, 'settings.html'), 'w', encoding='utf-8') as f:
        f.write(settings_template)

    logger.info("✅ HTML templates created successfully")

# Запуск фонового потока обновлений
def start_background_updates():
    """Запуск фонового обновления данных"""
    update_thread = threading.Thread(target=background_data_updates, daemon=True)
    update_thread.start()
    logger.info("🔄 Background updates started")

if __name__ == '__main__':
    # Создаем шаблоны при первом запуске
    create_templates()
    
    # Запускаем фоновые обновления
    start_background_updates()
    
    # Запускаем приложение
    logger.info("🚀 Starting Web Admin Dashboard...")
    logger.info("📱 Open in browser: http://localhost:8080")  # ИЗМЕНЕН ПОРТ
    
    try:
        socketio.run(app, host='0.0.0.0', port=8081, debug=False)  # ИЗМЕНЕН ПОРТ
    except KeyboardInterrupt:
        logger.info("👋 Shutting down admin dashboard...")
    except Exception as e:
        logger.error(f"❌ Error starting server: {e}")

# ================================
# REQUIREMENTS_WEB.TXT
# ================================

# Создаем requirements файл
requirements_content = '''# requirements_web.txt - Зависимости для веб-админки

Flask==2.3.3
Flask-SocketIO==5.3.6
supabase==2.3.4
python-dotenv==1.0.0
python-socketio==5.8.0
python-engineio==4.7.1
'''

# Создаем файл requirements
with open('requirements_web.txt', 'w', encoding='utf-8') as f:
    f.write(requirements_content)

logger.info("✅ Created requirements_web.txt")