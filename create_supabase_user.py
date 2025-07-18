# create_supabase_user.py

import os
import uuid
from supabase import create_client, Client
from dotenv import load_dotenv

def main():
    """
    Creates a new user in Supabase for testing purposes.
    """
    # Загружаем переменные из .env файла
    load_dotenv()

    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("❌ Ошибка: Убедитесь, что SUPABASE_URL и SUPABASE_KEY заданы в вашем .env файле.")
        return

    print("🔑 Supabase URL и Key найдены.")

    try:
        supabase: Client = create_client(url, key)
        print("✅ Успешно подключились к Supabase.")

        # Генерируем уникальный email, чтобы можно было запускать скрипт много раз
        random_part = str(uuid.uuid4())[:8]
        test_email = f"daniil.bystrov+test{random_part}@gmail.com"
        test_password = "password123"

        print(f"🔄 Создаем нового пользователя с email: {test_email}")

        # Создаем пользователя
        res = supabase.auth.sign_up({
            "email": test_email,
            "password": test_password,
        })

        if res.user:
            user_id = res.user.id
            print("\n" + "="*50)
            print("🎉 ПОЛЬЗОВАТЕЛЬ УСПЕШНО СОЗДАН! 🎉")
            print("="*50)
            print(f"📧 Email: {test_email}")
            print(f"🔑 Пароль: {test_password}")
            print(f"🆔 User ID (UUID): {user_id}")
            print("\n👉 Скопируйте этот User ID и используйте его в вашем curl запросе.")
            print("="*50 + "\n")
        else:
            print("❌ Не удалось создать пользователя.")
            if res.api_error:
                print(f"   Ошибка API: {res.api_error}")

    except Exception as e:
        print(f"❌ Произошла непредвиденная ошибка: {e}")
        print("   💡 Убедитесь, что ваши SUPABASE_URL и SUPABASE_KEY верны и активны.")

if __name__ == "__main__":
    # Установим зависимости, если их нет
    try:
        from supabase import create_client
        from dotenv import load_dotenv
    except ImportError:
        print("Не найдены нужные библиотеки. Устанавливаем...")
        import subprocess
        import sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "supabase", "python-dotenv"])
        print("✅ Библиотеки установлены. Запустите скрипт еще раз: python create_supabase_user.py")
        exit()
        
    main()