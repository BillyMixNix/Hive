"""Public diagnostics; exact unsanitized output hashes are recorded separately."""
import re
from urllib.parse import urlsplit


def safe_diagnostics(value):
    value = str(value)[-12000:]
    urls = []

    def url(match):
        try:
            p = urlsplit(match[0])
            allowed = {'maven.ftb.dev', 'maven.neoforged.net', 'maven.architectury.dev',
                       'repo.maven.apache.org', 'libraries.minecraft.net', 'plugins.gradle.org',
                       'services.gradle.org', 'docs.gradle.org', 'github.com',
                       'piston-meta.mojang.com', 'piston-data.mojang.com',
                       'resources.download.minecraft.net'}
            safe = f'{p.scheme}://{p.hostname}{p.path}' if p.hostname in allowed else '[redacted-url]'
        except ValueError:
            safe = '[redacted-url]'
        urls.append(safe)
        return f'HIVEPUBLICURL{len(urls)-1}END'

    value = re.sub(r'https?://[^\s\"\'<>]+', url, value)
    value = re.sub(r'(?<![A-Za-z0-9_])[A-Za-z]:[\\/][^\s\"\'<>]+', '<private-path>', value)
    value = re.sub(r'(?<![A-Za-z0-9/])/(?:[^\s\"\'<>:,)]+/?)+', '<container-path>', value)
    value = re.sub(r'(?i)(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,})', '[redacted]', value)
    value = re.sub(r'(?i)(authorization\s*:\s*bearer\s+)\S+', r'\1[redacted]', value)
    for i, safe in enumerate(urls):
        value = value.replace(f'HIVEPUBLICURL{i}END', safe)
    return value
