package app.locallexis

import android.app.Application

class App : Application() {
    val graph: AppGraph by lazy { AppGraph(this) }
}
