using System.Threading.Tasks;
using NUnit.Framework;

// Paralellik (e2e-java testng.xml: parallel="classes", 2 iş parçacığı): sınıflar paralel, en çok
// bayi sayısı kadar (2). Her test kendi fikstür örneğini alır; test durumu örnek alanlarındadır.
[assembly: Parallelizable(ParallelScope.Fixtures)]
[assembly: LevelOfParallelism(2)]
[assembly: FixtureLifeCycle(LifeCycle.InstancePerTestCase)]

namespace Antreklabs.Bayi.Altyapi;

/// <summary>Koşu düzeyi kurulum/kapanış: koşu sonunda paylaşılan tarayıcı kapatılır.</summary>
[SetUpFixture]
public sealed class Montaj
{
    [OneTimeTearDown]
    public Task KapatAsync() => Tarayici.KapatAsync();
}
