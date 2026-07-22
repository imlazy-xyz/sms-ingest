package xyz.imlazy.smsingest

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import xyz.imlazy.smsingest.setup.SetupScreen
import xyz.imlazy.smsingest.setup.SetupViewModel
import xyz.imlazy.smsingest.ui.theme.SmsIngestTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val container = (application as SmsIngestApplication).container
        setContent {
            SmsIngestTheme {
                Scaffold { innerPadding ->
                    val viewModel: SetupViewModel = viewModel(
                        factory = SetupViewModel.factory(
                            container.credentialStore,
                            container.keysetVerifier,
                        ),
                    )
                    SetupScreen(viewModel = viewModel, modifier = Modifier.padding(innerPadding))
                }
            }
        }
    }
}
