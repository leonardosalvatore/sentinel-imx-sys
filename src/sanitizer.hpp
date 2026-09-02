#pragma once
// Turns a raw log line into a stable "template" by replacing volatile tokens
// (PIDs, addresses, numbers, ...) with placeholders. Regex-free for speed and
// to keep dependencies minimal.

#include <string>

namespace sentinel {

// Produce a normalized template from a raw log line:
//  - lowercased, whitespace-collapsed
//  - [1234] / (1234) PID brackets      -> <PID>
//  - 0x-prefixed hex                    -> <HEX>
//  - dotted-quad IPv4                   -> <IP>
//  - UUIDs                              -> <UUID>
//  - remaining standalone integers      -> <NUM>
std::string sanitize(const std::string& raw);

}  // namespace sentinel
