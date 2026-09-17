plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
}

// Ported from Operit (LGPL-3.0-only) — see third_party/operit/LICENSE
//
// Changes vs upstream Operit:
//  - namespace: com.ai.assistance.quickjs -> com.psyche.kelivo.quickjs
//  - dropped version-catalog aliases (Kelivo has no libs.versions.toml)
//  - dropped kotlinx-serialization (verified unused by the ported sources)
//  - Java/Kotlin target aligned with the Kelivo app module (11)
//  - ndkVersion pinned to the same value as the Kelivo app module
//  - ABI list extended to match Kelivo (armeabi-v7a / arm64-v8a / x86_64)
android {
    namespace = "com.psyche.kelivo.quickjs"
    compileSdk = 36
    ndkVersion = "28.2.13676358"

    defaultConfig {
        minSdk = 24 // aligned with the Kelivo app (flutter.minSdkVersion)
        externalNativeBuild {
            cmake {
                cppFlags("-std=c++17")
            }
        }
        ndk {
            abiFilters.addAll(listOf("armeabi-v7a", "arm64-v8a", "x86_64"))
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
        debug {
            isMinifyEnabled = false
        }
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_11
    }
}