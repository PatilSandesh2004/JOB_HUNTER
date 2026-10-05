from backend.app.core.config import settings


def main():
    print("Application:", settings.app_name)
    print("Version:", settings.app_version)
    print("Environment:", settings.environment)
    print("SearXNG URL:", settings.searxng_url)


if __name__ == "__main__":
    main()