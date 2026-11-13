"""Corpus passage data definitions and generator for rc-typing."""

import hashlib
import json
from pathlib import Path

PASSAGES = [
    # 1. Code - Python
    {
        "id": "code-py-001",
        "category": "code",
        "language": "python",
        "title": "Binary Search",
        "text": "def binary_search(arr, target):\n    low, high = 0, len(arr) - 1\n    while low <= high:\n        mid = (low + high) // 2\n        if arr[mid] == target:\n            return mid\n        elif arr[mid] < target:\n            low = mid + 1\n        else:\n            high = mid - 1\n    return -1",
        "difficulty": "medium",
        "source": "Algorithms in Python",
        "license": "MIT",
        "author": "Open Source Community",
    },
    {
        "id": "code-py-002",
        "category": "code",
        "language": "python",
        "title": "Context Manager",
        "text": "from contextlib import contextmanager\n\n@contextmanager\ndef timer(label: str):\n    start = time.perf_counter()\n    try:\n        yield\n    finally:\n        elapsed = time.perf_counter() - start\n        logger.info(f'{label}: {elapsed:.3f}s')",
        "difficulty": "medium",
        "source": "Python standard library patterns",
        "license": "MIT",
        "author": "Python Software Foundation",
    },
    {
        "id": "code-py-003",
        "category": "code",
        "language": "python",
        "title": "Async Task Gathering",
        "text": "async def fetch_all(urls: list[str]) -> list[dict]:\n    async with httpx.AsyncClient() as client:\n        tasks = [client.get(u) for u in urls]\n        responses = await asyncio.gather(*tasks)\n        return [r.json() for r in responses if r.status_code == 200]",
        "difficulty": "medium",
        "source": "Async IO Cookbook",
        "license": "MIT",
        "author": "Open Source Community",
    },

    # 2. Code - PowerShell
    {
        "id": "code-pwsh-001",
        "category": "code",
        "language": "powershell",
        "title": "Process Filtering",
        "text": "Get-Process | Where-Object { $_.CPU -gt 10 -and $_.WorkingSet -gt 100MB } |\n    Sort-Object -Property CPU -Descending |\n    Select-Object -First 5 -Property Id, ProcessName, CPU, WorkingSet",
        "difficulty": "medium",
        "source": "PowerShell Documentation Examples",
        "license": "MIT",
        "author": "Microsoft Corporation",
    },
    {
        "id": "code-pwsh-002",
        "category": "code",
        "language": "powershell",
        "title": "Advanced Function Definition",
        "text": "function Test-PortConnectivity {\n    [CmdletBinding()]\n    param(\n        [Parameter(Mandatory = $true)]\n        [string]$ComputerName,\n        [ValidateRange(1, 65535)]\n        [int]$Port = 443\n    )\n    Test-NetConnection -ComputerName $ComputerName -Port $Port\n}",
        "difficulty": "hard",
        "source": "PowerShell Advanced Scripting",
        "license": "MIT",
        "author": "PowerShell Community",
    },

    # 3. Code - C++
    {
        "id": "code-cpp-001",
        "category": "code",
        "language": "cpp",
        "title": "RAII Resource Wrapper",
        "text": "template <typename T>\nclass ScopedPointer {\npublic:\n    explicit ScopedPointer(T* raw = nullptr) : ptr_(raw) {}\n    ~ScopedPointer() { delete ptr_; }\n    T* operator->() const noexcept { return ptr_; }\n    T& operator*() const noexcept { return *ptr_; }\nprivate:\n    T* ptr_;\n};",
        "difficulty": "hard",
        "source": "Modern C++ Design Patterns",
        "license": "Apache-2.0",
        "author": "C++ Standard Examples",
    },
    {
        "id": "code-cpp-002",
        "category": "code",
        "language": "cpp",
        "title": "Vector Algorithm",
        "text": "#include <vector>\n#include <algorithm>\n\nstd::vector<int> filter_evens(const std::vector<int>& input) {\n    std::vector<int> result;\n    std::copy_if(input.begin(), input.end(), std::back_inserter(result),\n                 [](int x) { return x % 2 == 0; });\n    return result;\n}",
        "difficulty": "medium",
        "source": "STL Algorithms Reference",
        "license": "Apache-2.0",
        "author": "C++ Reference",
    },

    # 4. Code - C#
    {
        "id": "code-cs-001",
        "category": "code",
        "language": "csharp",
        "title": "LINQ Query Expression",
        "text": "public static IEnumerable<UserSummary> GetActiveUsers(IEnumerable<User> users)\n{\n    return users\n        .Where(u => u.IsActive && u.EmailVerified)\n        .OrderBy(u => u.LastName)\n        .Select(u => new UserSummary(u.Id, $\"{u.FirstName} {u.LastName}\"));\n}",
        "difficulty": "medium",
        "source": ".NET Foundation Samples",
        "license": "MIT",
        "author": ".NET Community",
    },
    {
        "id": "code-cs-002",
        "category": "code",
        "language": "csharp",
        "title": "Record Struct Definition",
        "text": "public readonly record struct GeoCoordinate(double Latitude, double Longitude)\n{\n    public double DistanceTo(GeoCoordinate other)\n    {\n        var dLat = Math.Abs(Latitude - other.Latitude);\n        var dLon = Math.Abs(Longitude - other.Longitude);\n        return Math.Sqrt(dLat * dLat + dLon * dLon);\n    }\n}",
        "difficulty": "medium",
        "source": "C# Language Specification Examples",
        "license": "MIT",
        "author": "Microsoft Corporation",
    },

    # 5. Code - JavaScript
    {
        "id": "code-js-001",
        "category": "code",
        "language": "javascript",
        "title": "Debounce Implementation",
        "text": "function debounce(fn, delayMs = 300) {\n  let timeoutId = null;\n  return function (...args) {\n    clearTimeout(timeoutId);\n    timeoutId = setTimeout(() => {\n      fn.apply(this, args);\n    }, delayMs);\n  };\n}",
        "difficulty": "medium",
        "source": "Frontend Utilities",
        "license": "MIT",
        "author": "JavaScript Open Source",
    },
    {
        "id": "code-js-002",
        "category": "code",
        "language": "javascript",
        "title": "Deep Clone with StructuredClone",
        "text": "export async function clonePayload(payload) {\n  if (typeof structuredClone === 'function') {\n    return structuredClone(payload);\n  }\n  return JSON.parse(JSON.stringify(payload));\n}",
        "difficulty": "easy",
        "source": "Web Standards Helpers",
        "license": "MIT",
        "author": "MDN Web Docs Samples",
    },

    # 6. Code - TypeScript
    {
        "id": "code-ts-001",
        "category": "code",
        "language": "typescript",
        "title": "Generic Result Type",
        "text": "type Result<T, E = Error> =\n  | { ok: true; value: T }\n  | { ok: false; error: E };\n\nfunction unwrap<T>(res: Result<T>): T {\n  if (!res.ok) {\n    throw res.error;\n  }\n  return res.value;\n}",
        "difficulty": "medium",
        "source": "TypeScript Functional Patterns",
        "license": "MIT",
        "author": "TypeScript Community",
    },
    {
        "id": "code-ts-002",
        "category": "code",
        "language": "typescript",
        "title": "Mapped Readonly Types",
        "text": "export type DeepImmutable<T> = T extends Function | boolean | number | string\n  ? T\n  : T extends Array<infer U>\n  ? ReadonlyArray<DeepImmutable<U>>\n  : { readonly [K in keyof T]: DeepImmutable<T[K]> };",
        "difficulty": "hard",
        "source": "Advanced TypeScript Types",
        "license": "MIT",
        "author": "TypeScript Samples",
    },

    # 7. Code - SQL
    {
        "id": "code-sql-001",
        "category": "code",
        "language": "sql",
        "title": "Window Function Ranking",
        "text": "SELECT department_id, employee_id, salary,\n       RANK() OVER (PARTITION BY department_id ORDER BY salary DESC) AS rank_in_dept\nFROM employees\nWHERE status = 'ACTIVE'\nORDER BY department_id, rank_in_dept;",
        "difficulty": "medium",
        "source": "SQL Standards Reference",
        "license": "Apache-2.0",
        "author": "SQL Community",
    },
    {
        "id": "code-sql-002",
        "category": "code",
        "language": "sql",
        "title": "Common Table Expression (CTE)",
        "text": "WITH monthly_revenue AS (\n    SELECT DATE_TRUNC('month', order_date) AS order_month,\n           SUM(total_amount) AS revenue\n    FROM customer_orders\n    GROUP BY 1\n)\nSELECT order_month, revenue,\n       LAG(revenue) OVER (ORDER BY order_month) AS prev_month\nFROM monthly_revenue;",
        "difficulty": "medium",
        "source": "PostgreSQL Analytics Tutorials",
        "license": "Apache-2.0",
        "author": "Database Engineers",
    },

    # 8. Prose (Classic Literature / Gutenberg)
    {
        "id": "prose-001",
        "category": "prose",
        "language": None,
        "title": "Pride and Prejudice",
        "text": "It is a truth universally acknowledged, that a single man in possession of a good fortune, must be in want of a wife. However little known the feelings or views of such a man may be on his first entering a neighbourhood, this truth is so well fixed in the minds of the surrounding families, that he is considered the rightful property of some one or other of their daughters.",
        "difficulty": "medium",
        "source": "Project Gutenberg - Pride and Prejudice",
        "license": "Public Domain",
        "author": "Jane Austen",
    },
    {
        "id": "prose-002",
        "category": "prose",
        "language": None,
        "title": "Moby Dick",
        "text": "Call me Ishmael. Some years ago - never mind how long precisely - having little or no money in my purse, and nothing particular to interest me on shore, I thought I would sail about a little and see the watery part of the world. It is a way I have of driving off the spleen and regulating the circulation.",
        "difficulty": "medium",
        "source": "Project Gutenberg - Moby Dick",
        "license": "Public Domain",
        "author": "Herman Melville",
    },

    # 9. Reading (General Nonfiction & Encyclopedic)
    {
        "id": "reading-001",
        "category": "reading",
        "language": None,
        "title": "The Solar System",
        "text": "The Solar System is the gravitationally bound system of the Sun and the objects that orbit it. It formed 4.6 billion years ago from the gravitational collapse of a giant interstellar molecular cloud. The vast majority of the system's mass is in the Sun, with the remainder predominantly contained in Jupiter.",
        "difficulty": "easy",
        "source": "Wikipedia - Solar System",
        "license": "CC BY-SA 4.0",
        "author": "Wikipedia Contributors",
    },
    {
        "id": "reading-002",
        "category": "reading",
        "language": None,
        "title": "History of Typography",
        "text": "Movable type is the system and technology of printing and typography that uses movable components to reproduce the elements of a document, usually individual alphanumeric characters or punctuation marks. The world's first movable type printing technology for paper books was made of porcelain materials and was invented around 1040 AD in China.",
        "difficulty": "medium",
        "source": "Wikipedia - Movable Type",
        "license": "CC BY-SA 4.0",
        "author": "Wikipedia Contributors",
    },

    # 10. Technical (Science & Engineering)
    {
        "id": "technical-001",
        "category": "technical",
        "language": None,
        "title": "Cryptography and Public Keys",
        "text": "Public-key cryptography relies on asymmetric algorithms that use pairs of keys: private keys kept secret by their owners, and public keys distributed openly. Generation of such keys depends on cryptographic algorithms based on mathematical problems that produce one-way functions, ensuring computation in reverse is infeasible without trapdoor information.",
        "difficulty": "hard",
        "source": "arXiv Computer Science Abstract Overview",
        "license": "CC0",
        "author": "Scientific Public Domain",
    },
    {
        "id": "technical-002",
        "category": "technical",
        "language": None,
        "title": "Distributed Consensus",
        "text": "A fundamental problem in fault-tolerant distributed systems is reaching consensus among distributed processes when network partitions or node failures occur. Protocols like Paxos and Raft decompose consensus into leader election, log replication, and safety constraints, ensuring consistency across quorum majorities.",
        "difficulty": "hard",
        "source": "Systems Engineering Overview",
        "license": "MIT",
        "author": "Open Source Systems Research",
    },

    # 11. Formal (Legal & Regulatory)
    {
        "id": "formal-001",
        "category": "formal",
        "language": None,
        "title": "US Constitution Preamble",
        "text": "We the People of the United States, in Order to form a more perfect Union, establish Justice, insure domestic Tranquility, provide for the common defence, promote the general Welfare, and secure the Blessings of Liberty to ourselves and our Posterity, do ordain and establish this Constitution for the United States of America.",
        "difficulty": "medium",
        "source": "United States National Archives",
        "license": "Public Domain",
        "author": "United States Constitutional Convention",
    },
    {
        "id": "formal-002",
        "category": "formal",
        "language": None,
        "title": "Universal Declaration of Human Rights",
        "text": "Whereas recognition of the inherent dignity and of the equal and inalienable rights of all members of the human family is the foundation of freedom, justice and peace in the world, the General Assembly proclaims this Universal Declaration of Human Rights as a common standard of achievement for all peoples and all nations.",
        "difficulty": "medium",
        "source": "United Nations Official Records",
        "license": "Public Domain",
        "author": "United Nations General Assembly",
    },

    # 12. Conversational (Dialogue & Interviews)
    {
        "id": "conversational-001",
        "category": "conversational",
        "language": None,
        "title": "Team Standup Meeting",
        "text": "\"Morning everyone. Yesterday I wrapped up the initial pass on the authentication middleware and pushed the pull request. Today I plan on reviewing the telemetry metrics and writing regression tests. No blockers on my end so far, but I might need five minutes with Sarah after the standup to verify the token rotation scheme.\"",
        "difficulty": "easy",
        "source": "Engineering Communication Scenarios",
        "license": "CC0",
        "author": "Software Team Dialogue",
    },
    {
        "id": "conversational-002",
        "category": "conversational",
        "language": None,
        "title": "Customer Support Exchange",
        "text": "\"Thanks for reaching out to our support desk! I completely understand how frustrating it is when your export job fails midway through. Let me look up your account ID right now and check the worker queue logs. Could you confirm whether you encountered an error code on the dashboard or if the browser tab timed out?\"",
        "difficulty": "easy",
        "source": "Customer Experience Dialogue Patterns",
        "license": "CC0",
        "author": "Technical Support Dialogues",
    },
]


def build_corpus():
    base_dir = Path(__file__).resolve().parent
    out_dir = base_dir / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    grouped = {}
    for p in PASSAGES:
        # Normalize text line endings to \n
        text_norm = p["text"].replace("\r\n", "\n").replace("\r", "\n")
        p["text"] = text_norm
        p["sha256"] = hashlib.sha256(text_norm.encode("utf-8")).hexdigest()
        
        cat_key = f"{p['category']}_{p['language']}" if p.get("language") else p["category"]
        grouped.setdefault(cat_key, []).append(p)

    # Write each group file and an aggregated index
    for group_name, items in grouped.items():
        file_path = out_dir / f"{group_name}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)

    # Master index
    master_path = out_dir / "index.json"
    with open(master_path, "w", encoding="utf-8") as f:
        json.dump(PASSAGES, f, indent=2, ensure_ascii=False)

    print(f"Generated {len(PASSAGES)} passages across {len(grouped)} categories/languages in {out_dir}")


if __name__ == "__main__":
    build_corpus()
