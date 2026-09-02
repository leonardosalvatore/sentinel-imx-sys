#include "sanitizer.hpp"

#include <cctype>

namespace sentinel {

namespace {

bool is_digit(char c) { return c >= '0' && c <= '9'; }
bool is_hex(char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); }

// Count consecutive characters satisfying pred starting at i.
std::size_t run(const std::string& s, std::size_t i, bool (*pred)(char)) {
    std::size_t j = i;
    while (j < s.size() && pred(s[j])) ++j;
    return j - i;
}

// hex{8}-hex{4}-hex{4}-hex{4}-hex{12}
std::size_t match_uuid(const std::string& s, std::size_t i) {
    const int groups[] = {8, 4, 4, 4, 12};
    std::size_t p = i;
    for (int g = 0; g < 5; ++g) {
        if (g > 0) {
            if (p >= s.size() || s[p] != '-') return 0;
            ++p;
        }
        std::size_t got = run(s, p, is_hex);
        if (got < static_cast<std::size_t>(groups[g])) return 0;
        // must be exactly this many hex before the delimiter/end
        if (got > static_cast<std::size_t>(groups[g])) return 0;
        p += groups[g];
    }
    return p - i;
}

// d{1,3}(.d{1,3}){3}
std::size_t match_ipv4(const std::string& s, std::size_t i) {
    std::size_t p = i;
    for (int g = 0; g < 4; ++g) {
        if (g > 0) {
            if (p >= s.size() || s[p] != '.') return 0;
            ++p;
        }
        std::size_t got = run(s, p, is_digit);
        if (got < 1 || got > 3) return 0;
        p += got;
    }
    // Reject if immediately followed by another dotted number (not an address).
    if (p < s.size() && (s[p] == '.' && p + 1 < s.size() && is_digit(s[p + 1]))) return 0;
    return p - i;
}

// 0x<hex>+
std::size_t match_hex(const std::string& s, std::size_t i) {
    if (i + 2 >= s.size()) return 0;
    if (s[i] != '0' || s[i + 1] != 'x') return 0;
    std::size_t got = run(s, i + 2, is_hex);
    if (got == 0) return 0;
    return 2 + got;
}

// [digits] or (digits)
std::size_t match_bracket_pid(const std::string& s, std::size_t i) {
    if (s[i] != '[' && s[i] != '(') return 0;
    char close = (s[i] == '[') ? ']' : ')';
    std::size_t got = run(s, i + 1, is_digit);
    if (got == 0) return 0;
    std::size_t p = i + 1 + got;
    if (p >= s.size() || s[p] != close) return 0;
    return (p - i) + 1;
}

}  // namespace

std::string sanitize(const std::string& raw) {
    std::string s;
    s.reserve(raw.size());
    for (char c : raw) s.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));

    std::string out;
    out.reserve(s.size());

    const std::size_t n = s.size();
    std::size_t i = 0;
    while (i < n) {
        std::size_t len = 0;

        if ((len = match_hex(s, i))) {
            out += "<HEX>";
            i += len;
        } else if ((len = match_uuid(s, i))) {
            out += "<UUID>";
            i += len;
        } else if ((len = match_ipv4(s, i))) {
            out += "<IP>";
            i += len;
        } else if ((s[i] == '[' || s[i] == '(') && (len = match_bracket_pid(s, i))) {
            out += "<PID>";
            i += len;
        } else if (is_digit(s[i])) {
            out += "<NUM>";
            i += run(s, i, is_digit);
        } else {
            out.push_back(s[i]);
            ++i;
        }
    }

    // Collapse whitespace and trim.
    std::string collapsed;
    collapsed.reserve(out.size());
    bool in_space = false;
    for (char c : out) {
        if (std::isspace(static_cast<unsigned char>(c))) {
            in_space = true;
            continue;
        }
        if (in_space && !collapsed.empty()) collapsed.push_back(' ');
        in_space = false;
        collapsed.push_back(c);
    }
    return collapsed;
}

}  // namespace sentinel
