#!/usr/bin/env python3
"""
Скрипт для проверки типов user_id в проекте
Показывает где используется int (❌) и где str (✅)
"""

import os
import re
from typing import List, Dict, Tuple
from dataclasses import dataclass
from pathlib import Path


@dataclass
class UserIdUsage:
    file_path: str
    line_number: int
    line_content: str
    type_detected: str  # 'int', 'str', 'unknown'
    context: str  # 'function_param', 'class_field', 'variable', 'endpoint'


class UserIdChecker:
    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.usages: List[UserIdUsage] = []
        
        # Паттерны для поиска user_id с типами
        self.patterns = [
            # Параметры функций: user_id: int, user_id: str
            (r'user_id\s*:\s*(int|str)', 'function_param'),
            # Поля класса/модели: user_id: int = Field(...)
            (r'user_id\s*:\s*(int|str)(?:\s*=.*)?', 'class_field'),
            # FastAPI path parameters: {user_id} с типом в функции
            (r'def\s+\w+\([^)]*user_id\s*:\s*(int|str)', 'endpoint'),
            # Переменные с аннотациями: user_id: int = ...
            (r'^\s*user_id\s*:\s*(int|str)\s*=', 'variable'),
        ]
    
    def scan_file(self, file_path: Path) -> List[UserIdUsage]:
        """Сканирует один файл на наличие user_id"""
        usages = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except (UnicodeDecodeError, PermissionError):
            return usages
            
        for line_num, line in enumerate(lines, 1):
            for pattern, context in self.patterns:
                matches = re.finditer(pattern, line)
                for match in matches:
                    type_detected = match.group(1)
                    usages.append(UserIdUsage(
                        file_path=str(file_path.relative_to(self.project_root)),
                        line_number=line_num,
                        line_content=line.strip(),
                        type_detected=type_detected,
                        context=context
                    ))
        
        return usages
    
    def scan_project(self) -> None:
        """Сканирует весь проект"""
        python_files = list(self.project_root.rglob("*.py"))
        
        for file_path in python_files:
            # Пропускаем виртуальные окружения и кэш
            if any(part in str(file_path) for part in ['.venv', 'venv', '__pycache__', '.git']):
                continue
                
            file_usages = self.scan_file(file_path)
            self.usages.extend(file_usages)
    
    def get_status_emoji(self, type_detected: str) -> str:
        """Возвращает эмодзи для типа"""
        return "✅" if type_detected == "str" else "❌"
    
    def print_results(self) -> None:
        """Выводит результаты проверки"""
        if not self.usages:
            print("🔍 Не найдено использований user_id с типами в проекте")
            return
        
        print("🔍 Проверка типов user_id в проекте:")
        print("=" * 60)
        
        # Группируем по файлам
        files_dict: Dict[str, List[UserIdUsage]] = {}
        for usage in self.usages:
            if usage.file_path not in files_dict:
                files_dict[usage.file_path] = []
            files_dict[usage.file_path].append(usage)
        
        # Выводим результаты по файлам
        for file_path, file_usages in sorted(files_dict.items()):
            print(f"\n📁 {file_path}")
            print("-" * 40)
            
            for usage in file_usages:
                status = self.get_status_emoji(usage.type_detected)
                print(f"{status} Строка {usage.line_number}: user_id: {usage.type_detected}")
                print(f"   Контекст: {usage.context}")
                print(f"   Код: {usage.line_content}")
                print()
        
        # Статистика
        int_count = sum(1 for u in self.usages if u.type_detected == "int")
        str_count = sum(1 for u in self.usages if u.type_detected == "str")
        
        print("=" * 60)
        print("📊 Статистика:")
        print(f"❌ user_id: int  - {int_count} использований")
        print(f"✅ user_id: str  - {str_count} использований")
        print(f"📝 Всего найдено - {len(self.usages)} использований")
        
        if int_count > 0:
            print(f"\n⚠️  Найдено {int_count} использований int для user_id!")
            print("💡 Рекомендуется изменить их на str для UUID")
    
    def get_files_to_fix(self) -> List[str]:
        """Возвращает список файлов, которые нужно исправить"""
        files_with_int = set()
        for usage in self.usages:
            if usage.type_detected == "int":
                files_with_int.add(usage.file_path)
        return list(files_with_int)


def main():
    # Можно передать путь к проекту как аргумент
    import sys
    project_path = sys.argv[1] if len(sys.argv) > 1 else "."
    
    checker = UserIdChecker(project_path)
    checker.scan_project()
    checker.print_results()
    
    # Показываем файлы для исправления
    files_to_fix = checker.get_files_to_fix()
    if files_to_fix:
        print(f"\n🔧 Файлы для исправления ({len(files_to_fix)}):")
        for file_path in files_to_fix:
            print(f"   - {file_path}")


if __name__ == "__main__":
    main()