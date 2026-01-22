import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from "https://esm.sh/@supabase/supabase-js@2"

serve(async (req) => {
  try {
    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    )

    // 1. Get historical data (last 72 samples = 3 days for better patterns)
    const { data: history, error: fetchError } = await supabase
      .from('grid_telemetry')
      .select('overall_intensity, fuel_wind_perc, fuel_solar_perc, fuel_gas_perc, fuel_nuclear_perc')
      .order('timestamp', { ascending: false })
      .limit(72)

    if (fetchError) {
      console.error('Error fetching historical data:', fetchError)
      return new Response(
        JSON.stringify({ error: 'Failed to fetch historical data' }),
        { status: 500 }
      )
    }

    if (!history || history.length === 0) {
      console.log('No historical data available')
      return new Response(
        JSON.stringify({ message: 'No historical data available' }),
        { status: 200 }
      )
    }

    // Extract values for each metric type
    const metrics = {
      'Overall_Intensity': history.map(d => d.overall_intensity).reverse(),
      'Wind': history.map(d => d.fuel_wind_perc).reverse(),
      'Solar': history.map(d => d.fuel_solar_perc).reverse(),
      'Gas': history.map(d => d.fuel_gas_perc).reverse(),
      'Nuclear': history.map(d => d.fuel_nuclear_perc).reverse()
    }
    
    // Helper function: Smooth data to remove outliers
    function smoothData(values: number[]): number[] {
      if (values.length < 3) return values
      return values.map((val, i) => {
        if (i === 0 || i === values.length - 1) return val
        // Moving average with window of 3
        return (values[i - 1] + val + values[i + 1]) / 3
      })
    }

    // Helper function: Generate statistical forecast
    function statisticalForecast(values: number[], length: number): number[] {
      const avg = values.reduce((a, b) => a + b, 0) / values.length
      const trend = (values[values.length - 1] - values[0]) / values.length
      const volatility = Math.sqrt(
        values.reduce((sum, val) => sum + Math.pow(val - avg, 2), 0) / values.length
      )
      
      return Array.from({ length }, (_, i) => {
        const trendComponent = trend * (i + 1)
        const seasonalNoise = volatility * Math.sin((i * Math.PI) / 12)
        const randomNoise = (Math.random() - 0.5) * volatility * 0.3
        return avg + trendComponent + seasonalNoise + randomNoise
      })
    }

    // Smooth data for better predictions
    for (const key of Object.keys(metrics)) {
      metrics[key] = smoothData(metrics[key])
    }
    
    console.log(`Fetched and smoothed ${history.length} historical data points for all metrics`)

    // 2 & 3. Generate and store predictions for each metric
    let allPredictions = []
    
    for (const [metricType, values] of Object.entries(metrics)) {
      console.log(`\n=== Forecasting ${metricType} ===`)
      
      // Try Hugging Face API
      let forecast
      
      const models = [
        "amazon/chronos-t5-tiny",
        "facebook/dino-vitb16",
        "meta-llama/Llama-2-7b"
      ]
      
      let hfResponse
      
      for (const model of models) {
        try {
          console.log(`Trying model: ${model}`)
          hfResponse = await fetch(
            `https://api-inference.huggingface.co/models/${model}`,
            {
              headers: { Authorization: `Bearer ${hfToken}` },
              method: "POST",
              body: JSON.stringify({ inputs: values, parameters: { prediction_length: 24 } }),
            }
          )
          
          if (hfResponse.ok || hfResponse.status === 503) {
            break
          }
        } catch (e) {
          console.log(`Model ${model} failed: ${e}`)
        }
      }

      // If HF API fails, use simple statistical forecast
      if (!hfResponse || !hfResponse.ok) {
        console.log('HF API unavailable, using statistical forecast')
        forecast = statisticalForecast(values, 24)
      } else {
        const responseData = await hfResponse.json()
        const hfForecast = Array.isArray(responseData) ? responseData : responseData.forecast || responseData.predictions || []
        
        if (hfForecast.length === 0) {
          forecast = statisticalForecast(values, 24)
        } else {
          // Ensemble: Blend HF forecast (70%) with statistical forecast (30%)
          const statForecast = statisticalForecast(values, 24)
          forecast = hfForecast.slice(0, 24).map((hfVal: number, i: number) => 
            hfVal * 0.7 + statForecast[i] * 0.3
          )
          console.log(`Ensemble forecast: 70% HF + 30% statistical`)
        }
      }

      // Create predictions for this metric
      const metricPredictions = forecast.map((val: number, i: number) => {
        let predValue = typeof val === 'number' ? val : parseFloat(String(val))
        if (isNaN(predValue)) predValue = 50
        
        // Clamp values based on metric type
        if (metricType === 'Overall_Intensity') {
          predValue = Math.max(0, Math.min(1000, predValue)) // 0-1000 gCO2/kWh
        } else {
          predValue = Math.max(0, Math.min(100, predValue)) // 0-100% for fuel percentages
        }
        
        return {
          fuel_type: metricType,
          predicted_value: predValue,
          prediction_timestamp: new Date(Date.now() + (i + 1) * 3600000).toISOString()
        }
      })
      
      allPredictions = allPredictions.concat(metricPredictions)
      console.log(`Generated ${metricPredictions.length} predictions for ${metricType}`)
    }

    // Insert all predictions at once
    const { error: insertError } = await supabase
      .from('grid_predictions')
      .insert(allPredictions)

    if (insertError) {
      console.error('Error storing predictions:', insertError)
      return new Response(
        JSON.stringify({ error: 'Failed to store predictions' }),
        { status: 500 }
      )
    }

    console.log(`Successfully stored ${allPredictions.length} total predictions (${allPredictions.length / 5} per metric type)`)

    return new Response(
      JSON.stringify({ 
        success: true,
        message: `Generated ${allPredictions.length} predictions for 5 metrics (Overall_Intensity, Wind, Solar, Gas, Nuclear) - 24 hour forecast`,
        predictions: allPredictions
      }),
      { status: 200, headers: { 'Content-Type': 'application/json' } }
    )
  } catch (error) {
    console.error('Unexpected error:', error)
    return new Response(
      JSON.stringify({ error: String(error) }),
      { status: 500 }
    )
  }
})
